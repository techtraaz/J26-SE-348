import type { AuditCase } from "@/types/audit";

// Same sample as Backend Component-03 mock_data.json. UI works before backends are ready.
export const sampleCase: AuditCase = {
  case_id: "CASE-TV",
  docs: [
    {
      doc_id: "BS26", case_id: "CASE-TV", doc_type: "balance_sheet", period_year: 2026,
      parent_doc_id: null, fields: { assets: 40000, liabilities: 30000, capital: 20000 },
      confidences: {}, methods: {},
    },
    {
      doc_id: "INV1", case_id: "CASE-TV", doc_type: "invoice", period_year: 2026,
      parent_doc_id: "BS26", fields: { amount: 250000 },
      confidences: { amount: 0.42 }, methods: { amount: "ocr" },
    },
  ],
};

export const sampleFindings = [
  {
    finding_id: "BS26-CHK001", rule_id: "CHK-001", category: "ledger",
    severity: "high", message: "Equation broken in BS26: assets 40000 != liabilities 30000 + capital 20000.",
    evidence_ids: ["BS26"], policy_ids: ["CHK-001"], confidence: 1,
  },
  {
    finding_id: "INV1-POL-07", rule_id: "POL-07", category: "compliance",
    severity: "high", message: "Purchases above Rs. 100,000 need dual approval. Got 250000 in INV1.",
    evidence_ids: ["INV1"], policy_ids: ["POL-07"], confidence: 0.9,
  },
];
