"""
Memory Builder
Stage 1: Semantic Structured Compression (Section 3.1)
& Stage 2: Online Semantic Synthesis (Section 3.2)
Implements:
- Implicit semantic density gating: Φ_gate(W) → {m_k} (filters low-density windows)
- Sliding window processing for dialogue segmentation
- Generates compact memory units with resolved coreferences and absolute timestamps
"""
from typing import List, Optional, Dict
from ..models.memory_entry import MemoryEntry, Dialogue
from ..utils.llm_client import LLMClient
from ..database.vector_store import VectorStore
from .. import config
import json
import asyncio
import concurrent.futures
from functools import partial


class MemoryBuilder:
    """
    Memory Builder - Semantic Structured Compression (Section 3.1)

    Core Functions:
    1. Sliding window segmentation
    2. Implicit semantic density gating: Φ_gate(W) → {m_k}
    3. Multi-view indexing: I(m_k) = {s_k, l_k, r_k}
    4. Intra-session consolidation during write (Section 3.2): by generating enough memory entries to ensure ALL information is captured
    """
    def __init__(
        self,
        llm_client: LLMClient,
        vector_store: VectorStore,
        window_size: int = None,
        enable_parallel_processing: bool = True,
        max_parallel_workers: int = 3
    ):
        self.llm_client = llm_client
        self.vector_store = vector_store
        self.window_size = window_size or config.WINDOW_SIZE
        self.overlap_size = getattr(config, 'OVERLAP_SIZE', 0)
        # step_size is how far the window advances each iteration; overlap retains
        # the last overlap_size dialogues so the next window has continuity context
        self.step_size = max(1, self.window_size - self.overlap_size)

        # Use config values as default if not explicitly provided
        self.enable_parallel_processing = enable_parallel_processing if enable_parallel_processing is not None else getattr(config, 'ENABLE_PARALLEL_PROCESSING', True)
        self.max_parallel_workers = max_parallel_workers if max_parallel_workers is not None else getattr(config, 'MAX_PARALLEL_WORKERS', 4)

        # Dialogue buffer
        self.dialogue_buffer: List[Dialogue] = []
        self.processed_count = 0

        # Multi-Agent: Track session_id for each dialogue
        self._session_mapping: Dict[int, str] = {}

        # NOTE: previous_entries removed - now fetch from DB dynamically

    def add_dialogue(self, dialogue: Dialogue, session_id: str = None, auto_process: bool = True):
        """
        Add a dialogue to the buffer

        Args:
            dialogue: Dialogue object
            session_id: Session UUID (for multi-agent tracking)
            auto_process: Whether to auto-process when buffer is full
        """
        self.dialogue_buffer.append(dialogue)

        # Track session_id
        if session_id:
            self._session_mapping[dialogue.dialogue_id] = session_id

        # Auto process (disabled for now - process_window needs session_id)
        # Multi-agent mode: caller should manage when to process
        # if auto_process and len(self.dialogue_buffer) >= self.window_size:
        #     self.process_window(session_id=session_id)

    def add_dialogues(self, dialogues: List[Dialogue], auto_process: bool = True):
        """
        Batch add dialogues with optional parallel processing
        """
        if self.enable_parallel_processing and len(dialogues) > self.window_size * 2:
            # Use parallel processing for large batches
            self.add_dialogues_parallel(dialogues)
        else:
            # Use sequential processing for smaller batches
            for dialogue in dialogues:
                self.add_dialogue(dialogue, auto_process=False)

            # Process complete windows
            if auto_process:
                while len(self.dialogue_buffer) >= self.window_size:
                    self.process_window()
    
    def add_dialogues_parallel(self, dialogues: List[Dialogue]):
        """
        Add dialogues using parallel processing for better performance
        """
        # Snapshot pre-existing buffer items so the fallback can restore them
        # if the buffer is cleared mid-way through parallel processing
        pre_existing = list(self.dialogue_buffer)
        windows_to_process = []
        try:
            # Add all dialogues to buffer first
            self.dialogue_buffer.extend(dialogues)

            # Group into windows using step_size so that each window retains
            # overlap_size dialogues of context from the previous window
            pos = 0
            while pos + self.window_size <= len(self.dialogue_buffer):
                window = self.dialogue_buffer[pos:pos + self.window_size]
                windows_to_process.append(window)
                pos += self.step_size

            # Add remaining dialogues as a smaller batch (no need to process separately)
            remaining = self.dialogue_buffer[pos:]
            if remaining:
                windows_to_process.append(remaining)
            self.dialogue_buffer = []  # Clear buffer since we're processing all

            if windows_to_process:
                print(f"\n[Parallel Processing] Processing {len(windows_to_process)} batches in parallel with {self.max_parallel_workers} workers")
                print(f"Batch sizes: {[len(w) for w in windows_to_process]}")

                # Process all windows/batches in parallel (including remaining dialogues)
                self._process_windows_parallel(windows_to_process)

        except Exception as e:
            print(f"[Parallel Processing] Failed: {e}. Falling back to sequential processing...")
            # Fallback: overlapping windows cannot be re-stacked naively.
            # If the buffer was cleared (exception after line 107), restore the full
            # original state: pre-existing items that were already in the buffer
            # PLUS the new dialogues we were asked to process.
            # If the buffer was NOT cleared (exception before line 107), it already
            # contains pre_existing + dialogues, so leave it as-is.
            if not self.dialogue_buffer:
                self.dialogue_buffer = pre_existing + list(dialogues)
            # process_window() uses step_size, so overlap is handled correctly here
            while len(self.dialogue_buffer) >= self.window_size:
                self.process_window()

    def process_window(self, session_id: str = None):
        """
        Process current window dialogues - Core logic

        Args:
            session_id: Session UUID (for multi-agent tracking)
        """
        if not self.dialogue_buffer:
            return

        # Extract window; advance by step_size to retain overlap_size dialogues
        # at the tail so the next window has continuity context
        window = self.dialogue_buffer[:self.window_size]
        self.dialogue_buffer = self.dialogue_buffer[self.step_size:]

        print(f"\nProcessing window: {len(window)} dialogues (processed {self.processed_count} so far)")

        # Call LLM to generate memory entries (with DB context fetch)
        entries = self._generate_memory_entries(window, session_id=session_id)

        # Set session_id
        if session_id:
            for entry in entries:
                if not entry.session_id:
                    entry.session_id = session_id

        # Store to database
        if entries:
            self.vector_store.add_entries(entries)
            # NOTE: previous_entries removed - context now fetched from DB
            self.processed_count += len(window)

        print(f"Generated {len(entries)} memory entries")

    def process_remaining(self, session_id: str = None) -> List[MemoryEntry]:
        """
        Process remaining dialogues (Multi-Agent: returns entries instead of storing)

        Args:
            session_id: Session UUID (used to fetch context from DB)

        Returns:
            List of generated MemoryEntry (caller should store them)
        """
        if not self.dialogue_buffer:
            return []

        print(f"\nProcessing remaining dialogues: {len(self.dialogue_buffer)}")

        # Generate memory entries (fetches context from DB using session_id)
        entries = self._generate_memory_entries(self.dialogue_buffer, session_id=session_id)

        # Set session_id for all generated entries
        if session_id:
            for entry in entries:
                if not entry.session_id:
                    entry.session_id = session_id

        self.processed_count += len(self.dialogue_buffer)
        self.dialogue_buffer = []

        print(f"Generated {len(entries)} memory entries")

        return entries  # Return entries instead of storing directly

    def _generate_memory_entries(self, dialogues: List[Dialogue], session_id: str = None) -> List[MemoryEntry]:
        """
        Implicit Semantic Density Gating (Section 3.1)
        Φ_gate(W) → {m_k}, generates compact memory units from dialogue window

        Multi-Agent: Fetches context from DB instead of RAM

        Args:
            dialogues: List of dialogues to process
            session_id: Session UUID (used to fetch recent memories from DB)

        Returns:
            List of MemoryEntry
        """
        # Build dialogue text
        dialogue_text = "\n".join([str(d) for d in dialogues])
        dialogue_ids = [d.dialogue_id for d in dialogues]

        # Build context: Fetch from DB instead of using self.previous_entries
        context = ""
        if session_id and hasattr(self.vector_store, 'get_recent_entries'):
            try:
                # Fetch最近 3 條記憶作為上下文
                recent_entries = self.vector_store.get_recent_entries(
                    session_id=session_id,
                    limit=3
                )

                if recent_entries:
                    context = "\n[Previous Memory Entries from this session (for reference to avoid duplication)]\n"
                    for entry in recent_entries:
                        context += f"- {entry.lossless_restatement}\n"
            except Exception as e:
                print(f"Warning: Failed to fetch recent entries: {e}")

        # Build prompt
        prompt = self._build_extraction_prompt(dialogue_text, dialogue_ids, context)

        # Call LLM
        messages = [
            {
                "role": "system",
                "content": "You are a professional information extraction assistant, skilled at extracting structured, unambiguous information from conversations. You must output valid JSON format."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        # Retry up to 3 times if parsing fails
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use JSON format if configured
                response_format = None
                if hasattr(config, 'USE_JSON_FORMAT') and config.USE_JSON_FORMAT:
                    response_format = {"type": "json_object"}

                response = self.llm_client.chat_completion(
                    messages,
                    temperature=0.1,
                    response_format=response_format
                )

                # Parse response
                entries = self._parse_llm_response(response, dialogue_ids)
                return entries

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Attempt {attempt + 1}/{max_retries} failed to parse LLM response: {e}")
                    print(f"Retrying...")
                else:
                    print(f"All {max_retries} attempts failed to parse LLM response: {e}")
                    print(f"Raw response: {response[:500] if 'response' in locals() else 'No response'}")
                    return []

    def _build_extraction_prompt(
        self,
        dialogue_text: str,
        dialogue_ids: List[int],
        context: str
    ) -> str:
        """
        Build LLM extraction prompt
        """
        return f"""
Your task is to extract all valuable information from the following dialogues and convert them into structured memory entries.

{context}

[Current Window Dialogues]
{dialogue_text}

[Requirements]
1. **Complete Coverage**: Generate enough memory entries to ensure ALL information in the dialogues is captured
2. **Force Disambiguation**: Absolutely PROHIBIT using pronouns (he, she, it, they, this, that) and relative time (yesterday, today, last week, tomorrow)
3. **Lossless Information**: Each entry's lossless_restatement must be a complete, independent, understandable sentence
4. **Precise Extraction**:
   - keywords: Core keywords (names, places, entities, topic words)
   - timestamp: Absolute time in ISO 8601 format (if explicit time mentioned in dialogue)
   - location: Specific location name (if mentioned)
   - persons: All person names mentioned
   - entities: Companies, products, organizations, etc.
   - topic: The topic of this information

[Output Format]
Return a JSON array, each element is a memory entry:

```json
[
  {{
    "lossless_restatement": "Complete unambiguous restatement (must include all subjects, objects, time, location, etc.)",
    "keywords": ["keyword1", "keyword2", ...],
    "timestamp": "YYYY-MM-DDTHH:MM:SS or null",
    "location": "location name or null",
    "persons": ["name1", "name2", ...],
    "entities": ["entity1", "entity2", ...],
    "topic": "topic phrase"
  }},
  ...
]
```

[Example]
Dialogues:
[2025-11-15T14:30:00] Alice: Bob, let's meet at Starbucks tomorrow at 2pm to discuss the new product
[2025-11-15T14:31:00] Bob: Okay, I'll prepare the materials

Output:
```json
[
  {{
    "lossless_restatement": "Alice suggested at 2025-11-15T14:30:00 to meet with Bob at Starbucks on 2025-11-16T14:00:00 to discuss the new product.",
    "keywords": ["Alice", "Bob", "Starbucks", "new product", "meeting"],
    "timestamp": "2025-11-16T14:00:00",
    "location": "Starbucks",
    "persons": ["Alice", "Bob"],
    "entities": ["new product"],
    "topic": "Product discussion meeting arrangement"
  }},
  {{
    "lossless_restatement": "Bob agreed to attend the meeting and committed to prepare relevant materials.",
    "keywords": ["Bob", "prepare materials", "agree"],
    "timestamp": null,
    "location": null,
    "persons": ["Bob"],
    "entities": [],
    "topic": "Meeting preparation confirmation"
  }}
]
```

Now process the above dialogues. Return ONLY the JSON array, no other explanations.
"""

    def _parse_llm_response(
        self,
        response: str,
        dialogue_ids: List[int]
    ) -> List[MemoryEntry]:
        """
        Parse LLM response to MemoryEntry list
        """
        # Extract JSON
        data = self.llm_client.extract_json(response)

        if isinstance(data, dict):
            for key in ("entries", "memories", "items", "data"):
                candidate = data.get(key)
                if isinstance(candidate, list):
                    data = candidate
                    break
            else:
                list_values = [value for value in data.values() if isinstance(value, list)]
                if len(list_values) == 1:
                    data = list_values[0]

        if not isinstance(data, list):
            raise ValueError(f"Expected JSON array but got: {type(data)}")

        entries = []
        for item in data:
            # Create MemoryEntry
            entry = MemoryEntry(
                lossless_restatement=item["lossless_restatement"],
                keywords=item.get("keywords", []),
                timestamp=item.get("timestamp"),
                location=item.get("location"),
                persons=item.get("persons", []),
                entities=item.get("entities", []),
                topic=item.get("topic")
            )
            entries.append(entry)

        return entries
    
    def _process_windows_parallel(self, windows: List[List[Dialogue]], session_id: str = None):
        """
        Process multiple windows in parallel using ThreadPoolExecutor

        Args:
            windows: List of dialogue windows to process
            session_id: Session UUID (passed to workers for context fetching)
        """
        all_entries = []

        # Use ThreadPoolExecutor for parallel processing
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_parallel_workers) as executor:
            # Submit all window processing tasks
            future_to_window = {}
            for i, window in enumerate(windows):
                dialogue_ids = [d.dialogue_id for d in window]
                future = executor.submit(
                    self._generate_memory_entries_worker,
                    window,
                    dialogue_ids,
                    i+1,
                    session_id  # Pass session_id to worker
                )
                future_to_window[future] = (window, i+1)

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_window):
                window, window_num = future_to_window[future]
                try:
                    entries = future.result()
                    all_entries.extend(entries)
                    print(f"[Parallel Processing] Window {window_num} completed: {len(entries)} entries")
                except Exception as e:
                    print(f"[Parallel Processing] Window {window_num} failed: {e}")

        # Set session_id for all entries
        if session_id:
            for entry in all_entries:
                if not entry.session_id:
                    entry.session_id = session_id

        # Store all entries to database in batch
        if all_entries:
            print(f"\n[Parallel Processing] Storing {len(all_entries)} entries to database...")
            self.vector_store.add_entries(all_entries)
            self.processed_count += sum(len(window) for window in windows)

            # NOTE: previous_entries removed - context now fetched from DB

        print(f"[Parallel Processing] Completed processing {len(windows)} windows")
    
    def _generate_memory_entries_worker(self, window: List[Dialogue], dialogue_ids: List[int], window_num: int, session_id: str = None) -> List[MemoryEntry]:
        """
        Worker function for parallel processing of a single batch (full window or remaining dialogues)

        Args:
            window: List of dialogues
            dialogue_ids: List of dialogue IDs
            window_num: Worker number
            session_id: Session UUID (for fetching context from DB)

        Returns:
            List of MemoryEntry
        """
        batch_size = len(window)
        batch_type = "full window" if batch_size == self.window_size else f"remaining batch"
        print(f"[Worker {window_num}] Processing {batch_type} with {batch_size} dialogues")

        # Build dialogue text
        dialogue_text = "\n".join([str(d) for d in window])

        # Build context: Fetch from DB
        context = ""
        if session_id and hasattr(self.vector_store, 'get_recent_entries'):
            try:
                recent_entries = self.vector_store.get_recent_entries(
                    session_id=session_id,
                    limit=3
                )

                if recent_entries:
                    context = "\n[Previous Memory Entries from this session (for reference)]\n"
                    for entry in recent_entries:
                        context += f"- {entry.lossless_restatement}\n"
            except Exception as e:
                print(f"[Worker {window_num}] Warning: Failed to fetch context: {e}")

        # Build prompt
        prompt = self._build_extraction_prompt(dialogue_text, dialogue_ids, context)

        # Call LLM
        messages = [
            {
                "role": "system",
                "content": "You are a professional information extraction assistant, skilled at extracting structured, unambiguous information from conversations. You must output valid JSON format."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]

        # Retry up to 3 times if parsing fails
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use JSON format if configured
                response_format = None
                if hasattr(config, 'USE_JSON_FORMAT') and config.USE_JSON_FORMAT:
                    response_format = {"type": "json_object"}

                response = self.llm_client.chat_completion(
                    messages,
                    temperature=0.1,
                    response_format=response_format
                )

                # Parse response
                entries = self._parse_llm_response(response, dialogue_ids)
                print(f"[Worker {window_num}] Generated {len(entries)} entries")
                return entries

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[Worker {window_num}] Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying...")
                else:
                    print(f"[Worker {window_num}] All {max_retries} attempts failed: {e}")
                    return []
