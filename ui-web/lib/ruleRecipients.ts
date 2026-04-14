const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_PATTERN = /^\+?[1-9]\d{7,14}$/;

export function normalizeRuleRecipientEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function isValidRuleRecipientEmail(email: string): boolean {
  return EMAIL_PATTERN.test(normalizeRuleRecipientEmail(email));
}

export function dedupeRuleRecipientEmails(emails: string[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const email of emails) {
    const normalized = normalizeRuleRecipientEmail(email);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    ordered.push(normalized);
  }
  return ordered;
}

export function normalizeRuleRecipientPhone(phone: string): string {
  const cleaned = phone.trim().replace(/[^\d+]/g, "");
  if (cleaned.startsWith("00")) {
    return `+${cleaned.slice(2)}`;
  }
  return cleaned.startsWith("+") ? cleaned : `+${cleaned}`;
}

export function isValidRuleRecipientPhone(phone: string): boolean {
  const normalized = normalizeRuleRecipientPhone(phone);
  return PHONE_PATTERN.test(normalized);
}

export function dedupeRuleRecipientPhones(phones: string[]): string[] {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const phone of phones) {
    const normalized = normalizeRuleRecipientPhone(phone);
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    if (!isValidRuleRecipientPhone(normalized)) {
      continue;
    }
    seen.add(normalized);
    ordered.push(normalized);
  }
  return ordered;
}
