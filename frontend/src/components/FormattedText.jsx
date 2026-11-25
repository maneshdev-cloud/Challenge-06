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
  const blocks = [];
  let bulletBuffer = [];

  function flushBullets(keyPrefix) {
    if (!bulletBuffer.length) return;
    blocks.push(
      <ul key={`ul-${keyPrefix}`} className="space-y-1.5 pl-1">
        {bulletBuffer.map((itemText, itemIdx) => (
          <li key={itemIdx} className="flex items-start gap-2">
            <span
              aria-hidden="true"
              className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                dark ? "bg-teal-300" : "bg-teal-600"
              }`}
            />
            <span>{renderInlineBold(itemText)}</span>
          </li>
        ))}
      </ul>
    );
    bulletBuffer = [];
  }

  lines.forEach((rawLine, idx) => {
    const line = rawLine.trim();
    if (!line) {
      flushBullets(idx);
      blocks.push(<div key={`gap-${idx}`} className="h-1" />);
      return;
    }

    if (line.startsWith("- ") || line.startsWith("* ")) {
      bulletBuffer.push(line.slice(2).trim());
      return;
    }

    flushBullets(idx);

    const cleanPlain = line.replace(/\*\*/g, "");
    const isSectionHeader =
      cleanPlain.endsWith(":") &&
      cleanPlain.length <= 42 &&
      !line.startsWith("-") &&
      !line.startsWith("*");

    if (isSectionHeader) {
      blocks.push(
        <p
          key={`hdr-${idx}`}
          className={`pt-1 text-xs font-extrabold uppercase tracking-wider ${
            dark ? "text-teal-300" : "text-teal-800"
          }`}
        >
          {cleanPlain}
        </p>
      );
      return;
    }

    blocks.push(<p key={`p-${idx}`}>{renderInlineBold(line)}</p>);
  });

  flushBullets("end");

  return <div className="space-y-1.5 leading-relaxed">{blocks}</div>;
}
