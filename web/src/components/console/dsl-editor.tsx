"use client";

import Editor, { loader, type Monaco, type OnMount } from "@monaco-editor/react";
import { useTheme } from "next-themes";
import { useEffect, useRef } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { DslIssue } from "@/lib/api/schemas";
import { LANGUAGE_ID, registerWardenLanguage, THEMES } from "@/lib/monaco";

loader.config({ paths: { vs: "/monaco/vs" } });

type EditorInstance = Parameters<OnMount>[0];

export interface DslEditorHandle {
  reveal: (line: number, column: number) => void;
}

export function DslEditor({
  value,
  onChange,
  issues,
  readOnly = false,
  onReady,
  onSave,
}: {
  value: string;
  onChange: (value: string) => void;
  issues: DslIssue[];
  readOnly?: boolean;
  onReady?: (handle: DslEditorHandle) => void;
  onSave?: () => void;
}) {
  const { resolvedTheme } = useTheme();
  const monacoRef = useRef<Monaco | null>(null);
  const editorRef = useRef<EditorInstance | null>(null);
  const saveRef = useRef(onSave);
  saveRef.current = onSave;

  useEffect(() => {
    const monaco = monacoRef.current;
    const model = editorRef.current?.getModel();
    if (!monaco || !model) return;
    monaco.editor.setModelMarkers(
      model,
      LANGUAGE_ID,
      issues.map((issue) => ({
        startLineNumber: issue.line,
        startColumn: issue.column,
        endLineNumber: issue.end_line,
        endColumn: issue.end_column,
        message: issue.message,
        code: issue.code,
        severity: issue.severity === "error" ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
      })),
    );
  }, [issues]);

  return (
    <Editor
      height="100%"
      language={LANGUAGE_ID}
      theme={resolvedTheme === "dark" ? THEMES.dark : THEMES.light}
      value={value}
      onChange={(next) => onChange(next ?? "")}
      beforeMount={registerWardenLanguage}
      onMount={(editor, monaco) => {
        editorRef.current = editor;
        monacoRef.current = monaco;
        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveRef.current?.());
        onReady?.({
          reveal: (line, column) => {
            editor.revealLineInCenter(line);
            editor.setPosition({ lineNumber: line, column });
            editor.focus();
          },
        });
      }}
      loading={<Skeleton className="h-full w-full rounded-none" />}
      options={{
        readOnly,
        fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace',
        fontSize: 13,
        lineHeight: 21,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        renderLineHighlight: "line",
        padding: { top: 16, bottom: 16 },
        tabSize: 2,
        smoothScrolling: true,
        cursorBlinking: "smooth",
        overviewRulerBorder: false,
        guides: { indentation: true },
        automaticLayout: true,
        fixedOverflowWidgets: true,
        "semanticHighlighting.enabled": false,
      }}
    />
  );
}
