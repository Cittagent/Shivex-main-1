import test from "node:test";
import assert from "node:assert/strict";

import {
  dedupeRuleRecipientEmails,
  isValidRuleRecipientEmail,
  normalizeRuleRecipientEmail,
} from "../../lib/ruleRecipients.ts";

test("dedupeRuleRecipientEmails normalizes and dedupes recipient emails", () => {
  assert.deepEqual(
    dedupeRuleRecipientEmails([
      " OPS@PlantA.com ",
      "ops@planta.com",
      "guard@planta.com",
    ]),
    ["ops@planta.com", "guard@planta.com"],
  );
});

test("isValidRuleRecipientEmail validates recipient email format", () => {
  assert.equal(isValidRuleRecipientEmail("alerts@planta.com"), true);
  assert.equal(isValidRuleRecipientEmail("invalid-email"), false);
});

test("normalizeRuleRecipientEmail normalizes recipient emails consistently", () => {
  assert.equal(normalizeRuleRecipientEmail(" Guard@PlantA.com "), "guard@planta.com");
});
