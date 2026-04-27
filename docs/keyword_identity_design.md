# Keyword Identity Design

Mục tiêu của thiết kế này là tránh gom nhầm các keyword nhìn giống nhau nhưng intent khác nhau.

## 1. Phân loại quan hệ

- `alias`: biến thể ngôn ngữ của cùng một intent, SERP gần như trùng nhau.
- `same_root`: cùng root/topic, nhưng chưa đủ an toàn để gộp thành alias cứng.
- `sibling`: cùng topical border, nhưng intent khác và nên giữ thành node riêng.
- `reject`: lệch topical border hoặc có tín hiệu contamination rõ.

## 2. Tín hiệu chấm điểm

Thiết kế dùng 4 nhóm tín hiệu:

1. Lexical similarity
2. Intent modifier
3. SERP overlap
4. Topical scope của project

## 3. Rule ưu tiên

1. Loại `reject` trước nếu không cùng scope hoặc có contamination.
2. Chỉ cho `alias` khi:
   - cùng modifier group,
   - cùng root,
   - top 10 SERP overlap >= 5,
   - top 3 overlap >= 2.
3. Nếu cùng root nhưng modifier khác, mặc định hạ xuống `same_root` hoặc `sibling`.

## 4. Cách dùng trong pipeline

- Dùng trước khi chốt topical map.
- Dùng để audit các keyword nghi ngờ.
- Dùng để kiểm tra keyword nào cần gọi SERP lại.

## 5. Mẫu quyết định

- `Thi quỹ hàng hóa` và `Thi quỹ hàng hóa là gì`:
  - Nếu SERP trùng mạnh và cùng intent definitional -> `alias`.
- `Thi quỹ hàng hóa là gì` và `Thi quỹ hàng hóa có hợp pháp không`:
  - Cùng root, khác intent -> `sibling`.
- `Thi quỹ hàng hóa` và `Crypto trading`:
  - Khác topical border -> `reject`.
