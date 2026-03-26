"""
Test script to verify ltm package imports
"""
import sys
print("Python path:")
for p in sys.path:
    print(f"  {p}")

print("\n" + "="*60)
print("Testing ltm package imports...")
print("="*60)

try:
    print("\n1. Testing main import...")
    from ltm.simplemem import MultiAgentMemorySystem, create_system
    print("   ✓ Main classes imported successfully")
    print(f"   - MultiAgentMemorySystem: {MultiAgentMemorySystem}")
    print(f"   - create_system: {create_system}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n2. Testing package-level import...")
    from ltm import MultiAgentMemorySystem, create_system
    print("   ✓ Package-level import successful")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n3. Testing config import...")
    from ltm import config
    print("   ✓ Config imported successfully")
    print(f"   - QDRANT_URL: {config.QDRANT_URL}")
    print(f"   - POSTGRES_URL: {config.POSTGRES_URL}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n4. Testing core module imports...")
    from ltm.core import MemoryBuilder, HybridRetriever, AnswerGenerator
    print("   ✓ Core modules imported successfully")
    print(f"   - MemoryBuilder: {MemoryBuilder}")
    print(f"   - HybridRetriever: {HybridRetriever}")
    print(f"   - AnswerGenerator: {AnswerGenerator}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n5. Testing database module imports...")
    from ltm.database import QdrantVectorStore, PostgreSQLStore
    print("   ✓ Database modules imported successfully")
    print(f"   - QdrantVectorStore: {QdrantVectorStore}")
    print(f"   - PostgreSQLStore: {PostgreSQLStore}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n6. Testing models module imports...")
    from ltm.models import Dialogue, MemoryEntry
    print("   ✓ Models imported successfully")
    print(f"   - Dialogue: {Dialogue}")
    print(f"   - MemoryEntry: {MemoryEntry}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n7. Testing utils module imports...")
    from ltm.utils import LLMClient, EmbeddingModel
    print("   ✓ Utils imported successfully")
    print(f"   - LLMClient: {LLMClient}")
    print(f"   - EmbeddingModel: {EmbeddingModel}")
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*60)
print("Import test completed!")
print("="*60)
