import type { Monaco } from "@monaco-editor/react";

export const LANGUAGE_ID = "warden";
export const THEMES = { light: "warden-light", dark: "warden-dark" } as const;

const KEYWORDS = ["model", "schema", "type", "relations", "define", "or", "and", "but", "not", "from"];

let registered = false;

/** Registers the DSL grammar, editor behaviour and Xcode-like themes once per page. */
export function registerWardenLanguage(monaco: Monaco): void {
  if (registered) return;
  registered = true;

  monaco.languages.register({ id: LANGUAGE_ID, extensions: [".warden"] });
  monaco.languages.setMonarchTokensProvider(LANGUAGE_ID, {
    keywords: KEYWORDS,
    tokenizer: {
      root: [
        [/\/\/.*$/, "comment"],
        [/\b(type)(\s+)([A-Za-z_][\w-]*)/, ["keyword", "white", "type.identifier"]],
        [/\b(define)(\s+)([A-Za-z_][\w-]*)/, ["keyword", "white", "variable.name"]],
        [/\b(schema)(\s+)(\d+\.\d+)/, ["keyword", "white", "number"]],
        [/([A-Za-z_][\w-]*)(#)([A-Za-z_][\w-]*)/, ["type.identifier", "delimiter", "variable.name"]],
        [/([A-Za-z_][\w-]*)(:\*)/, ["type.identifier", "operator"]],
        [/[A-Za-z_][\w-]*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }],
        [/[[\]()]/, "@brackets"],
        [/[:,]/, "delimiter"],
        [/\s+/, "white"],
      ],
    },
  });
  monaco.languages.setLanguageConfiguration(LANGUAGE_ID, {
    comments: { lineComment: "//" },
    brackets: [
      ["[", "]"],
      ["(", ")"],
    ],
    autoClosingPairs: [
      { open: "[", close: "]" },
      { open: "(", close: ")" },
    ],
    surroundingPairs: [
      { open: "[", close: "]" },
      { open: "(", close: ")" },
    ],
    indentationRules: {
      increaseIndentPattern: /^\s*(type\s+\S+|relations)\s*$/,
      decreaseIndentPattern: /^\s*type\b/,
    },
  });
  monaco.languages.registerCompletionItemProvider(LANGUAGE_ID, {
    provideCompletionItems(model, position) {
      const word = model.getWordUntilPosition(position);
      const range = {
        startLineNumber: position.lineNumber,
        endLineNumber: position.lineNumber,
        startColumn: word.startColumn,
        endColumn: word.endColumn,
      };
      const identifiers = new Set(
        Array.from(model.getValue().matchAll(/\b(?:type|define)\s+([A-Za-z_][\w-]*)/g), (m) => m[1] ?? ""),
      );
      identifiers.delete("");
      return {
        suggestions: [
          ...KEYWORDS.map((label) => ({
            label,
            kind: monaco.languages.CompletionItemKind.Keyword,
            insertText: label,
            range,
          })),
          ...[...identifiers].map((label) => ({
            label,
            kind: monaco.languages.CompletionItemKind.Reference,
            insertText: label,
            range,
          })),
          {
            label: "define … from parent",
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertText: "define ${1:viewer}: [${2:user}] or ${3:editor} or ${1:viewer} from ${4:parent}",
            insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
            documentation: "A relation inherited through a parent object",
            range,
          },
        ],
      };
    },
  });

  monaco.editor.defineTheme(THEMES.light, {
    base: "vs",
    inherit: true,
    rules: [
      { token: "keyword", foreground: "9B2393", fontStyle: "bold" },
      { token: "type.identifier", foreground: "0B4F79" },
      { token: "variable.name", foreground: "326D74" },
      { token: "number", foreground: "1C00CF" },
      { token: "comment", foreground: "5D6C79", fontStyle: "italic" },
      { token: "operator", foreground: "9B2393" },
      { token: "delimiter", foreground: "6E6E73" },
    ],
    colors: {
      "editor.background": "#FFFFFF",
      "editor.lineHighlightBackground": "#F5F5F7",
      "editorLineNumber.foreground": "#AEAEB2",
      "editorLineNumber.activeForeground": "#1D1D1F",
      "editor.selectionBackground": "#B3D7FF",
      "editorCursor.foreground": "#0071E3",
      "editorIndentGuide.background1": "#E5E5EA",
    },
  });
  monaco.editor.defineTheme(THEMES.dark, {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "keyword", foreground: "FC5FA3", fontStyle: "bold" },
      { token: "type.identifier", foreground: "5DD8FF" },
      { token: "variable.name", foreground: "67B7A4" },
      { token: "number", foreground: "D0BF69" },
      { token: "comment", foreground: "6C7986", fontStyle: "italic" },
      { token: "operator", foreground: "FC5FA3" },
      { token: "delimiter", foreground: "98989D" },
    ],
    colors: {
      "editor.background": "#1C1C1E",
      "editor.lineHighlightBackground": "#2C2C2E",
      "editorLineNumber.foreground": "#636366",
      "editorLineNumber.activeForeground": "#F5F5F7",
      "editor.selectionBackground": "#3F638B",
      "editorCursor.foreground": "#0A84FF",
      "editorIndentGuide.background1": "#2C2C2E",
    },
  });
}
