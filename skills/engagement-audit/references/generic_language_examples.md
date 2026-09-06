# Generic vs. Specific Language Calibration Examples

This reference document provides illustrative calibration examples for the **invoking AI Agent** to evaluate extracted text descriptions for specificity and clarity.

> [!IMPORTANT]
> **Agent Calibration Notice**:
> These examples are strictly for calibrating the **invoking agent's qualitative judgment** when following `SKILL.md` instructions. No Python script in this skill reads, matches, or parses this file.

---

## Calibration Examples

### Example 1: Product / Offering Description
- ❌ **Generic / Marketing Fluff**:
  > "We offer industry-leading, cutting-edge software solutions designed to empower your business with maximum efficiency and high-quality results."
- ✅ **Concrete & Specific**:
  > "Our automated inventory tracking dashboard syncs stock levels across Shopify, Amazon, and WooCommerce every 60 seconds, reducing stockout oversights by 40%."

---

### Example 2: Service / Feature Explanation
- ❌ **Generic / Marketing Fluff**:
  > "Our experienced team delivers superior customer support with unmatched dedication to customer satisfaction."
- ✅ **Concrete & Specific**:
  > "Dedicated account managers respond to critical support tickets within 15 minutes, 24 hours a day, 7 days a week."

---

### Example 3: Value Proposition / Technical Spec
- ❌ **Generic / Marketing Fluff**:
  > "Built using state-of-the-art technology to ensure fast performance and great user experience."
- ✅ **Concrete & Specific**:
  > "Engineered with Rust and WebAssembly to process 100,000 data rows in under 50 milliseconds directly in the user's browser."

---

## Agent Guidance
When judging extracted description text:
1. **Specific Details**: Does the text cite exact numbers, specific technologies, measurable SLAs, or clear workflow actions?
2. **Generic Fluff**: Does the text rely heavily on buzzwords ("industry-leading", "cutting-edge", "best-in-class") without explaining *how* or *what*?
