import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { bootstrapAgentSoul } from "../../api/dashboard";
import type { BootstrapChatMessage } from "../../types/dashboard";

interface SoulBootstrapDialogProps {
  agentId: string;
  agentName: string;
  onClose: () => void;
  onSaved: (soul: string) => void;
}

const openingMessage = (agentName: string) =>
  `The new custom agent name is ${agentName}. Begin a short onboarding conversation to bootstrap its SOUL.`;

function speakerBadge(role: BootstrapChatMessage["role"], t: (key: string) => string) {
  if (role === "assistant") {
    return {
      icon: "SB",
      label: t("agents.agent.bootstrapAssistant"),
    };
  }
  return {
    icon: "你",
    label: t("agents.agent.bootstrapUser"),
  };
}

export default function SoulBootstrapDialog({
  agentId,
  agentName,
  onClose,
  onSaved,
}: SoulBootstrapDialogProps) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<BootstrapChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timelineEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      setLoading(true);
      setError(null);
      try {
        const result = await bootstrapAgentSoul(agentId, {
          message: openingMessage(agentName),
          history: [],
          mode: "bootstrap",
          save: false,
        });
        if (cancelled) {
          return;
        }
        setMessages([{ role: "assistant", content: result.reply ?? "" }]);
      } catch (err: unknown) {
        if (cancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void start();
    return () => {
      cancelled = true;
    };
  }, [agentId, agentName]);

  useEffect(() => {
    timelineEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function handleSend(save: boolean) {
    const message = draft.trim() || (save ? "Please save now." : "");
    if (!message) {
      return;
    }

    const nextHistory = [...messages, { role: "user" as const, content: message }];
    setMessages(nextHistory);
    setDraft("");
    setLoading(true);
    setError(null);

    try {
      const result = await bootstrapAgentSoul(agentId, {
        message,
        history: messages,
        mode: save ? "synthesis" : "bootstrap",
        save,
      });
      if (result.saved) {
        onSaved(result.soul ?? "");
        return;
      }
      setMessages([...nextHistory, { role: "assistant", content: result.reply ?? "" }]);
    } catch (err: unknown) {
      setMessages(messages);
      setDraft(message);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="agent-tab-modal" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        className="agent-tab-modal-inner agent-soul-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="agent-soul-dialog__header">
          <h2>{t("agents.agent.bootstrapTitle")}</h2>
          <p>{t("agents.agent.bootstrapSubtitle", { name: agentName })}</p>
        </div>

        <div className="agent-soul-dialog__timeline" aria-live="polite">
          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={`agent-soul-dialog__message agent-soul-dialog__message--${message.role}`}
            >
              <div className="agent-soul-dialog__message-head">
                <span className="agent-soul-dialog__avatar" aria-hidden="true">
                  {speakerBadge(message.role, t).icon}
                </span>
                <strong className="agent-soul-dialog__speaker">{speakerBadge(message.role, t).label}</strong>
              </div>
              <div className="agent-soul-dialog__bubble">
                <p>{message.content}</p>
              </div>
            </div>
          ))}
          {loading ? (
            <div className="agent-soul-dialog__message agent-soul-dialog__message--assistant">
              <div className="agent-soul-dialog__message-head">
                <span className="agent-soul-dialog__avatar" aria-hidden="true">SB</span>
                <strong className="agent-soul-dialog__speaker">
                  {t("agents.agent.bootstrapAssistant")}
                </strong>
              </div>
              <div className="agent-soul-dialog__bubble agent-soul-dialog__bubble--loading">
                <p>{t("agents.agent.bootstrapLoading")}</p>
              </div>
            </div>
          ) : null}
          <div ref={timelineEndRef} aria-hidden="true" />
        </div>

        <label className="agent-soul-dialog__composer">
          {t("agents.agent.bootstrapInputLabel")}
          <textarea
            rows={4}
            className="agent-soul-dialog__textarea"
            value={draft}
            disabled={loading}
            placeholder={t("agents.agent.bootstrapInputPlaceholder")}
            onChange={(e) => setDraft(e.target.value)}
          />
        </label>

        {error ? <p className="form-error">{error}</p> : null}

        <div className="modal-actions">
          <button onClick={() => void handleSend(false)} disabled={loading || !draft.trim()}>
            {t("agents.agent.bootstrapSendButton")}
          </button>
          <button onClick={() => void handleSend(true)} disabled={loading || messages.length === 0}>
            {t("agents.agent.bootstrapSaveButton")}
          </button>
          <button onClick={onClose} disabled={loading}>
            {t("agents.agent.cancelButton")}
          </button>
        </div>
      </div>
    </div>
  );
}
