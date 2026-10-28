import { createParser } from "@openuidev/lang-core";
import { openuiChatLibrary } from "@openuidev/react-ui/genui-lib";

/**
 * Turns an assistant message (OpenUI Lang) into plain sentences for
 * text-to-speech. It parses with the official OpenUI parser and reads the
 * human-facing text components; tables and charts are summarised by their
 * labels rather than read cell by cell.
 */

let parser: ReturnType<typeof createParser> | null = null;

function getParser() {
  parser ??= createParser(openuiChatLibrary.toJSONSchema(), "Card");
  return parser;
}

const TEXT_PROPS: Record<string, string[]> = {
  CardHeader: ["title", "subtitle"],
  TextContent: ["text"],
  MarkDownRenderer: ["textMarkdown"],
  Callout: ["title", "description"],
  TextCallout: ["title", "description"],
  InlineHeader: ["heading", "description"],
  MetricIndicatorInline: ["value", "subtext"],
  BoldText: ["value", "subtext"],
  Text: ["value", "subtext"],
  StepsItem: ["title", "details"],
};

type Node = { typeName?: string; props?: Record<string, unknown> };

function isNode(value: unknown): value is Node {
  return typeof value === "object" && value !== null && "typeName" in value;
}

function walk(value: unknown, out: string[], depth = 0) {
  if (depth > 40 || value == null) return;
  if (Array.isArray(value)) {
    value.forEach((item) => walk(item, out, depth + 1));
    return;
  }
  if (!isNode(value)) {
    if (typeof value === "object") Object.values(value as object).forEach((v) => walk(v, out, depth + 1));
    return;
  }
  const props = value.props ?? {};
  const keys = TEXT_PROPS[value.typeName ?? ""];
  if (keys) {
    for (const key of keys) {
      const text = props[key];
      if (typeof text === "string" && text.trim()) out.push(text.trim());
    }
  }
  if (value.typeName === "EntityList" && Array.isArray(props.rows)) {
    for (const row of props.rows as { left?: string; right?: string }[]) {
      if (row?.left && row?.right) out.push(`${row.left}: ${row.right}.`);
    }
  }
  if (value.typeName === "Table") {
    out.push("The full table is shown on screen.");
    return;
  }
  if (value.typeName === "FollowUpBlock" || value.typeName === "CodeBlock") return;
  Object.values(props).forEach((v) => walk(v, out, depth + 1));
}

function stripMarkdown(text: string) {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[(\d+)\]/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`#>|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function speakableText(openuiLang: string): string {
  if (!openuiLang.trim()) return "";
  try {
    const result = getParser().parse(openuiLang);
    const parts: string[] = [];
    walk(result.root, parts);
    return stripMarkdown(parts.join(". ").replace(/\.\s*\./g, "."));
  } catch {
    return "";
  }
}

export type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

export function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechSynthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
}
