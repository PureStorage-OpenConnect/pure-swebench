## Bug: Shift + Return does not continue nested (sub-level) list items in the compose box

### Environment
Zulip web app, message compose box.

### Steps to reproduce
1. In the compose box, type a nested bulleted list:
   ```
   - Message 1
     - Message 2
   ```
2. Place the caret at the end of the second line (the indented sub-list item `- Message 2`).
3. Press Shift + Return.

### Observed behavior
A plain new line is inserted without starting a new list item:
```
- Message 1
  - Message 2

```

### Expected behavior
Pressing Shift + Return at the end of a sub-list item should automatically start a new item at the same indentation level, matching the existing behavior for top-level (level 1) list items:
```
- Message 1
  - Message 2
  - 
```
