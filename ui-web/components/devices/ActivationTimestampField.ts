import { createElement } from "react";

import { formatIST } from "../../lib/utils.ts";

type ActivationTimestampFieldProps = {
  label: string;
  timestamp: string | null;
  emptyText?: string;
  className?: string;
  labelClassName?: string;
  valueClassName?: string;
};

export function ActivationTimestampField({
  label,
  timestamp,
  emptyText = "Not activated yet",
  className = "flex items-center justify-between text-sm",
  labelClassName = "text-slate-500",
  valueClassName = "text-xs text-slate-900",
}: ActivationTimestampFieldProps) {
  return createElement(
    "div",
    { className },
    createElement("span", { className: labelClassName }, label),
    createElement("span", { className: valueClassName }, formatIST(timestamp, emptyText)),
  );
}
