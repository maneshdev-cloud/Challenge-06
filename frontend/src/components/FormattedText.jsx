import React from "react";

function renderInlineBold(line) {
  const parts = line.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, idx) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return (
        <strong key={idx} className="font-bold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

export default function FormattedText({ text, dark = false }) {
  if (!text) return null;

  const lines = String(text).split("\n");
  return (
    <div className="space-y-1.5 leading-relaxed">
      {lines.map((rawLine, idx) => {
        const line = rawLine.trim();
        if (!line) {
          return <div key={idx} className="h-1" />;
        }

        const cleanPlain = line.replace(/\*\*/g, "");
        const isSectionHeader =
          cleanPlain.endsWith(":") &&
          cleanPlain.length <= 42 &&
          !line.startsWith("-") &&
          !line.startsWith("*");

        if (isSectionHeader) {
          return (
            <p
              key={idx}
              className={`pt-1 text-xs font-extrabold uppercase tracking-wider ${
                dark ? "text-teal-300" : "text-teal-800"
              }`}
            >
              {cleanPlain}
            </p>
          );
        }

        if (line.startsWith("- ") || line.startsWith("* ")) {
          const content = line.slice(2).trim();
          return (
            <div key={idx} className="flex items-start gap-2 pl-1">
              <span
                className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                  dark ? "bg-teal-300" : "bg-teal-600"
                }`}
              />
              <span>{renderInlineBold(content)}</span>
            </div>
          );
        }

        return <p key={idx}>{renderInlineBold(line)}</p>;
      })}
    </div>
  );
}
