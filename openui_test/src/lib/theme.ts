import { createTheme } from "@openuidev/react-ui";

/**
 * Queryable Chatbot tokens for OpenUI's ThemeProvider (passed through
 * <AgentInterface theme={...}>). Surfaces are translucent ink so the
 * cinematic aurora backdrop glows through; the brand accent is ember. Matching CSS
 * variables live in globals.css (--qc-*), so custom chrome and OpenUI
 * share one palette.
 *
 * Chart palettes: eight saturated hues ordered so neighbours never share
 * a hue family (blue, ember, teal, amber, violet, rose, green, sky). The
 * light set is one step deeper so every hue holds 3:1 against white.
 */
const DARK_SERIES = ["#6b9bff", "#ff7f5c", "#2fd0b0", "#ffc247", "#b98cff", "#ff6b9d", "#7ee08a", "#58c7ff"];
const LIGHT_SERIES = ["#2f6be0", "#e5532d", "#0f9e85", "#c98a00", "#8b52e0", "#d93a72", "#2f9a46", "#0f8fcf"];

const palettes = (series: string[]) => ({
  defaultChartPalette: series,
  barChartPalette: series,
  lineChartPalette: series,
  areaChartPalette: series,
  pieChartPalette: series,
  radarChartPalette: series,
  radialChartPalette: series,
  horizontalBarChartPalette: series,
});

const typography = {
  fontBody: "var(--font-sans), system-ui, sans-serif",
  fontHeading: "var(--font-sans), system-ui, sans-serif",
  fontLabel: "var(--font-sans), system-ui, sans-serif",
  fontNumbers: "var(--font-sans), system-ui, sans-serif",
};

export const queryableDarkTheme = createTheme({
  ...palettes(DARK_SERIES),
  ...typography,
  // Translucent surfaces: the aurora backdrop (globals.css) shows through.
  background: "transparent",
  foreground: "rgba(17, 19, 29, 0.72)",
  popoverBackground: "#151824",
  sunkLight: "rgba(255, 255, 255, 0.02)",
  sunk: "rgba(14, 16, 25, 0.66)",
  sunkDeep: "rgba(0, 0, 0, 0.4)",
  elevatedLight: "rgba(28, 31, 45, 0.7)",
  elevated: "rgba(30, 34, 49, 0.82)",
  elevatedStrong: "rgba(38, 43, 61, 0.9)",
  highlightSubtle: "rgba(255, 255, 255, 0.025)",
  highlight: "rgba(255, 255, 255, 0.06)",
  highlightStrong: "rgba(255, 255, 255, 0.1)",
  textNeutralPrimary: "#f1f2f8",
  textNeutralSecondary: "#b1b6c9",
  textNeutralTertiary: "#80869c",
  textNeutralLink: "#ffa285",
  textBrand: "#ff8f6b",
  textAccentPrimary: "#1c0c06",
  interactiveAccentDefault: "#ff7f5c",
  interactiveAccentHover: "#ff9878",
  interactiveAccentPressed: "#f0683f",
  borderDefault: "rgba(255, 255, 255, 0.07)",
  borderInteractive: "rgba(255, 255, 255, 0.12)",
  borderInteractiveEmphasis: "rgba(255, 255, 255, 0.22)",
  borderAccent: "rgba(255, 127, 92, 0.55)",
  chatUserResponseBg: "rgba(255, 127, 92, 0.16)",
  chatUserResponseText: "#fff3ee",
});

export const queryableLightTheme = createTheme({
  ...palettes(LIGHT_SERIES),
  ...typography,
  background: "transparent",
  foreground: "rgba(255, 255, 255, 0.7)",
  popoverBackground: "#ffffff",
  sunkLight: "rgba(255, 255, 255, 0.5)",
  sunk: "rgba(255, 255, 255, 0.72)",
  elevated: "rgba(255, 255, 255, 0.9)",
  highlightSubtle: "rgba(28, 30, 40, 0.025)",
  highlight: "rgba(28, 30, 40, 0.05)",
  highlightStrong: "rgba(28, 30, 40, 0.09)",
  textNeutralPrimary: "#1a1c25",
  textNeutralSecondary: "#515768",
  textNeutralTertiary: "#7a8091",
  textNeutralLink: "#c4441f",
  textBrand: "#c4441f",
  textAccentPrimary: "#ffffff",
  interactiveAccentDefault: "#d84a24",
  interactiveAccentHover: "#c4401c",
  interactiveAccentPressed: "#ad3816",
  borderDefault: "rgba(28, 30, 40, 0.08)",
  borderInteractive: "rgba(28, 30, 40, 0.13)",
  borderInteractiveEmphasis: "rgba(28, 30, 40, 0.24)",
  borderAccent: "rgba(216, 74, 36, 0.45)",
  chatUserResponseBg: "rgba(216, 74, 36, 0.1)",
  chatUserResponseText: "#2a130b",
});
