# Jotform incoming webhook: accept real (multipart) payloads and render file-upload answers as links

## Background

Zulip ships an incoming webhook integration for Jotform (`zerver/webhooks/jotform/`). When a form is submitted, Jotform does **not** send a JSON body: it delivers the webhook as a `multipart/form-data` POST. The parts relevant here are:

- `formTitle` (used for the topic), `submissionID`, and similar metadata parts.
- `pretty`: a single string containing the human-readable answers as `Label:Answer` entries joined by a comma and a space, in question order. Example: `Student's Name:Niloth P, Type of Tutoring:Online Tutoring, Subject for Tutoring:Math, Grade:12, Prior Tutoring?:No, Identity Proof:Student_ID_!_$&'()_,-.;=@[]^_`{}~ .png Driving.license.png, Reports:Report Card.pdf`
- `rawRequest`: a JSON document with the raw per-question answers. When the form has file-upload questions, `rawRequest` additionally contains, for each upload question, a top-level key named after the question (e.g. `identityProof`, `reports`) whose value is a **list of full, percent-encoded URLs** of the uploaded files on jotform.com, in upload order. Example: `"identityProof": ["https://www.jotform.com/uploads/UserNiloth/243231271343446/6111139644845227683/Student_ID_%21_%24%26%27%28%29_%2C-.%3B%3D%40%5B%5D%5E_%60%7B%7D~%20.png", "https://www.jotform.com/uploads/UserNiloth/243231271343446/6111139644845227684/Driving.license.png"]`.

Note the relationship between the two: for a file-upload question, the `pretty` answer lists the plain filenames (as Jotform sanitized them) separated by single spaces, and each such filename equals the URL-decoded final path segment of one of the URLs in the corresponding `rawRequest` list.

## Current behavior

The integration is broken for real Jotform traffic. The handler was written assuming a JSON request body, so genuine `multipart/form-data` submissions error out; and submissions containing file-upload questions are not rendered usefully (the upload answers are raw filename text, not links, and any naive comma/space splitting of `pretty` mangles filenames that contain spaces, commas, or other punctuation).

## Required behavior

On receiving a Jotform submission webhook (`multipart/form-data`), the endpoint must succeed and post one message whose body is a bullet list built from the `pretty` entries, in order, with these rules:

1. **Label formatting.** A label ending in `?` renders as `* **<label>** <value>` (the `?` stays inside the bold, then a space — no colon). Every other label renders as `* **<label>**: <value>`. (This colon-vs-question-mark distinction is existing behavior and must be preserved.)
2. **Non-file questions** render as consecutive bullet lines with no blank lines between them.
3. **File-upload questions** always appear as the trailing entries of the `pretty` field list (Jotform places them last). They must be detected there even when filenames contain spaces and special characters such as `!$&'(),-.;=@[]^_`{}~` — which rules out simple splitting; use the URL lists in `rawRequest` (URL-decode each URL's final path segment and match it against the text of the trailing `pretty` answers) to identify which trailing entries are file answers and where each filename starts and ends.
4. **File-upload rendering.** Each file-upload answer renders each uploaded file as a Markdown link `[<filename>](<file URL>)`, where the link text is the filename exactly as it appears in the `pretty` answer and the URL is the matching (still percent-encoded) URL from `rawRequest`. Multiple files for one question are joined with a comma and a space.
5. **Blank line before file bullets.** Every file-upload question's bullet line must be preceded by a blank line (this makes uploaded images render as previews in Zulip). Non-file bullets stay tightly packed per rule 2.
6. Topic and any leading message content keep their existing behavior (the topic comes from the form title); this work only changes payload parsing and the answer list rendering.

### Concrete example

Given the `pretty` and `rawRequest` values shown in Background (a form with five regular questions and two file-upload questions, `Identity Proof` with two files and `Reports` with one), the posted message body must be exactly:

```
* **Student's Name**: Niloth P
* **Type of Tutoring**: Online Tutoring
* **Subject for Tutoring**: Math
* **Grade**: 12
* **Prior Tutoring?** No

* **Identity Proof**: [Student_ID_!_$&'()_,-.;=@[]^_`{}~ .png](https://www.jotform.com/uploads/UserNiloth/243231271343446/6111139644845227683/Student_ID_%21_%24%26%27%28%29_%2C-.%3B%3D%40%5B%5D%5E_%60%7B%7D~%20.png), [Driving.license.png](https://www.jotform.com/uploads/UserNiloth/243231271343446/6111139644845227684/Driving.license.png)

* **Reports**: [Report Card.pdf](https://www.jotform.com/uploads/UserNiloth/243231271343446/6111139644845227685/Report%20Card.pdf)
```

A submission with no file-upload questions must continue to render as it does today (consecutive bullets, no trailing blank-line groups).

## Interface requirements

- When a Jotform submission includes file-upload questions, the webhook message must render each file-upload answer as Markdown links: for each uploaded file, `[<filename>](<file URL>)`, where the link text is the filename as shown in the submission's pretty-printed answer and the URL is the corresponding uploaded-file URL from the submission payload (matched by URL-decoded filename); multiple files for one question are joined with a comma and a space.
- Each file-upload question's bullet line in the message must be preceded by a blank line (so uploaded images render correctly in Zulip); non-file questions remain consecutive bullets with no blank lines between them.
- File-upload answers must be recognized as the trailing entries of the payload's pretty-printed field list (file-upload questions always appear last there), including filenames that contain spaces and special characters.
- Question labels ending in `?` must render as `* **<label>** <value>` (space separator, no colon), while all other labels render as `* **<label>**: <value>` — this is pre-existing behavior that must keep working, including in messages that contain file-upload answers.

## Notes for testing locally

Real Jotform requests can be reproduced in a dev environment via a tunneling service (ngrok, ultrahook, etc.) pointed at the local webhook endpoint; do not test against a production Zulip server, since the current code errors on real payloads.
