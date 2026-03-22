=== Fix 1: Intent Detection ===
  [PASS] 'thép tấm và thép cuộn khác nhau' -> vs (expected vs)
  [PASS] 'nên chọn iD14 hay là iD4' -> vs (expected vs)
  [PASS] 'động cơ bước là gì' -> informational (expected informational)
  [FAIL] 'cách sửa vòi hoa sen' -> informational (expected how-to)
  [PASS] 'thép tấm và thép cuộn khác nhau thế nào' -> vs (expected vs)
  [PASS] 'so sánh máy khoan Bosch và Makita' -> vs (expected vs)
  [FAIL] 'giá thép hình chữ H hôm nay' -> transactional (expected commercial)

=== Fix 2: H2 Minimum by Intent ===
  [PASS] vs -> 5
  [PASS] informational -> 4
  [PASS] how-to -> 4
  [PASS] general -> 3

=== Fix 3b: VS Symmetry Check ===
  [PASS] With comparison H2 -> True
  [PASS] Without comparison H2 -> False

=== Fix 4: Anchor Text ===
  [PASS] Exact reorders entity:attr
  [PASS] Has 'primary' key
  [PASS] Semantic uses 'gia' verb
  [PASS] Question adds 'la gi?' for definition
  [PASS] No 'tai sao nen' in any variant
  [PASS] No 'khi nao can' in any variant

=== Fix 6: SUPP Enforcer + PAA FAQ ===
  [PASS] FAQ H2 created
  [PASS] SUPP prefix exists
  [PASS] Antonym ending exists
  [PASS] PAA H3s added (>=1)
  Output headings (9 total):
    H2: [MAIN] Tinh nang chinh
    H2: [MAIN] Uu nhuoc diem
    H2: [MAIN] Gia ban
    H2: [MAIN] Ung dung
    H2: [SUPP] FAQ về May khoan Bosch
    H3: San pham nay co tot khong?
    H3: Nen mua o dau?
    H3: Bao hanh bao lau?
    H2: [SUPP] May khoan Bosch: Những trường hợp không nên sử dụng

=== Fix 5: Koray Prominence Penalty ===
  [PASS] Returns a string (markdown table)
  [PASS] Contains PROMINENCE PENALTY
  Score output (first 300 chars): ## 📊 KORAY QUALITY SCORE: **43/100** (Grade D)

| Tiêu chí | Điểm |
|----------|------|
| ✅ 1. Contextual Vector | 10/10 |
| ❌ 2. Contextual Hierarchy (H3) | 3/10 |
| ❌ 3. FS Blocks (≤60 từ) | 0/10 |
| ⚠️ 4. PAA Mapping | 5/10 |
| ✅ 5. Main/Supp Split | 10/10 |
| ❌ 6. EAV Coverage | 0/10 |
| ⚠️ 7. S

========================================
TOTAL: 23 passed, 2 failed
========================================