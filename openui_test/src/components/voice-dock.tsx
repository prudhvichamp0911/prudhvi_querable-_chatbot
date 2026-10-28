"use client";

import { useThread } from "@openuidev/react-ui";
import { Headphones, Mic, MicOff, Send, Square, Volume2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useBrowserCheck, useLocalStorage } from "@/lib/use-browser";
import {
  getSpeechRecognition,
  speakableText,
  speechSynthesisSupported,
  type SpeechRecognitionLike,
} from "@/lib/speech";

const AUTO_READ_KEY = "queryable-voice-autoread";

type Status = "idle" | "listening" | "review" | "error";

/**
 * Voice controls for the OpenUI chat. Rendered inside <AgentInterface>, so
 * a voice question goes through the same thread, the same /api/chat
 * endpoint and the same authenticated session as typed text.
 */
export function VoiceDock() {
  const processMessage = useThread((s) => s.processMessage);
  const isRunning = useThread((s) => s.isRunning);
  const messages = useThread((s) => s.messages);

  const supported = {
    input: useBrowserCheck(() => getSpeechRecognition() !== null),
    output: useBrowserCheck(speechSynthesisSupported),
  };
  const [status, setStatus] = useState<Status>("idle");
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [notice, setNotice] = useState("");
  const [autoReadValue, setAutoReadValue] = useLocalStorage(AUTO_READ_KEY);
  const autoRead = autoReadValue === "1";
  const [speaking, setSpeaking] = useState(false);

  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const wasRunning = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    return () => {
      recognitionRef.current?.abort();
      if (speechSynthesisSupported()) window.speechSynthesis.cancel();
    };
  }, []);

  const lastAnswer = useCallback(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const message = messages[i] as { role: string; content?: unknown };
      if (message.role === "assistant" && typeof message.content === "string" && message.content.trim()) {
        return message.content;
      }
    }
    return "";
  }, [messages]);

  const stopSpeaking = useCallback(() => {
    if (speechSynthesisSupported()) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  /** Speak an answer; returns false when it has no readable text. */
  const speak = useCallback((openuiLang: string) => {
    if (!speechSynthesisSupported()) return false;
    const text = speakableText(openuiLang);
    if (!text) return false;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 4000));
    utterance.lang = navigator.language || "en-US";
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
    return true;
  }, []);

  // Read the answer aloud when a run finishes, if the user opted in.
  useEffect(() => {
    if (wasRunning.current && !isRunning && autoRead) {
      const answer = lastAnswer();
      if (answer) speak(answer);
    }
    wasRunning.current = isRunning;
  }, [isRunning, autoRead, lastAnswer, speak]);

  const startListening = () => {
    const Recognition = getSpeechRecognition();
    if (!Recognition) {
      setStatus("error");
      setNotice("Voice input is not supported in this browser. Try Chrome or Edge — typing still works.");
      return;
    }
    stopSpeaking();
    const recognition = new Recognition();
    recognition.lang = navigator.language || "en-US";
    recognition.continuous = false;
    recognition.interimResults = true;

    let finalText = "";
    recognition.onresult = (event) => {
      let interimText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interimText += result[0].transcript;
      }
      setTranscript(finalText.trim());
      setInterim(interimText);
    };
    recognition.onerror = (event) => {
      const messagesByCode: Record<string, string> = {
        "not-allowed": "Microphone access was blocked. Allow it in the browser's site settings to use voice.",
        "service-not-allowed": "Speech recognition is disabled in this browser.",
        "no-speech": "No speech was detected. Try again.",
        "audio-capture": "No microphone was found.",
        network: "Speech recognition needs a network connection.",
      };
      setNotice(messagesByCode[event.error] ?? `Voice input stopped (${event.error}).`);
      setStatus(event.error === "no-speech" || event.error === "aborted" ? "review" : "error");
    };
    recognition.onend = () => {
      setInterim("");
      setStatus((current) => (current === "listening" ? "review" : current));
      recognitionRef.current = null;
    };

    recognitionRef.current = recognition;
    setTranscript("");
    setNotice("");
    setStatus("listening");
    try {
      recognition.start();
    } catch {
      setStatus("error");
      setNotice("Voice input could not start. Try again.");
    }
  };

  const stopListening = () => recognitionRef.current?.stop();

  useEffect(() => {
    if (status === "review") textareaRef.current?.focus();
  }, [status]);

  const close = () => {
    recognitionRef.current?.abort();
    setStatus("idle");
    setTranscript("");
    setInterim("");
    setNotice("");
  };

  const send = async () => {
    const text = transcript.trim();
    if (!text || isRunning) return;
    close();
    await processMessage({ role: "user", content: text });
  };

  const toggleAutoRead = () => {
    if (autoRead) stopSpeaking();
    setAutoReadValue(autoRead ? "0" : "1");
  };

  const readLastAnswer = () => {
    if (!speak(lastAnswer())) {
      setNotice("There is no readable text in the last answer.");
    }
  };

  const panelOpen = status !== "idle";

  return (
    <div className="voice-dock" aria-label="Voice controls">
      {panelOpen && (
        <div className="voice-panel" role="dialog" aria-label="Voice question">
          <div className="voice-panel__header">
            <span className={`voice-panel__state voice-panel__state--${status}`}>
              {status === "listening" ? "Listening…" : status === "error" ? "Voice unavailable" : "Review your question"}
            </span>
            <button type="button" className="voice-icon-button" onClick={close} aria-label="Close voice panel">
              <X size={16} />
            </button>
          </div>

          {status === "listening" && (
            <div className="voice-wave" aria-hidden="true">
              <span /><span /><span /><span /><span />
            </div>
          )}

          <label className="voice-panel__label" htmlFor="voice-transcript">
            Recognized text (you can edit it before sending)
          </label>
          <textarea
            id="voice-transcript"
            ref={textareaRef}
            className="voice-panel__text"
            rows={3}
            value={status === "listening" ? `${transcript} ${interim}`.trim() : transcript}
            readOnly={status === "listening"}
            onChange={(event) => setTranscript(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder={status === "listening" ? "Speak now…" : "Your question"}
          />

          <p className="voice-panel__notice" role="status" aria-live="polite">
            {notice}
          </p>

          <div className="voice-panel__actions">
            {status === "listening" ? (
              <button type="button" className="voice-button" onClick={stopListening}>
                <MicOff size={16} /> Stop
              </button>
            ) : (
              <button type="button" className="voice-button" onClick={startListening} disabled={!supported.input}>
                <Mic size={16} /> Record again
              </button>
            )}
            <button
              type="button"
              className="voice-button voice-button--primary"
              onClick={() => void send()}
              disabled={!transcript.trim() || status === "listening" || isRunning}
            >
              <Send size={16} /> Send
            </button>
          </div>
        </div>
      )}

      <div className="voice-dock__buttons">
        {supported.output && (
          <>
            <button
              type="button"
              className={`voice-fab ${autoRead ? "voice-fab--active" : ""}`}
              onClick={toggleAutoRead}
              aria-pressed={autoRead}
              aria-label="Read new answers aloud automatically"
              title={autoRead ? "Auto-read is on" : "Auto-read is off"}
            >
              <Headphones size={17} />
            </button>
            <button
              type="button"
              className="voice-fab"
              onClick={() => (speaking ? stopSpeaking() : readLastAnswer())}
              disabled={!speaking && !lastAnswer()}
              aria-label={speaking ? "Stop reading aloud" : "Read the last answer aloud"}
              title={speaking ? "Stop reading aloud" : "Read the last answer aloud"}
            >
              {speaking ? <Square size={16} /> : <Volume2 size={18} />}
            </button>
          </>
        )}
        <button
          type="button"
          className={`voice-fab voice-fab--mic ${status === "listening" ? "voice-fab--listening" : ""}`}
          onClick={status === "listening" ? stopListening : startListening}
          aria-label={status === "listening" ? "Stop voice input" : "Ask with your voice"}
          title={supported.input ? "Ask with your voice" : "Voice input is not supported in this browser"}
        >
          {status === "listening" ? <MicOff size={18} /> : <Mic size={18} />}
        </button>
      </div>
    </div>
  );
}
