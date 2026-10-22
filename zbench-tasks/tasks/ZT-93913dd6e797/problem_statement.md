# Jotform integration: correctly render form answers containing colons and commas

## Background

Zulip's Jotform webhook integration (`zerver/webhooks/jotform/`) receives form-submission notifications from Jotform as `multipart/form-data` POSTs. The parts of the payload relevant here are:

- `formTitle` — the human-readable form name (used as the message topic).
- `pretty` — a single string containing every answered question as `label:answer` entries joined with `", "` (comma + space). Example: `First Name:John, Last Name:Doe`.
- `rawRequest` — a JSON object holding the authoritative submitted answers. Question answers live under keys of the form `q<number>_<slug>` (e.g. `q10_key1With`); the object also contains bookkeeping keys (`slug`, `path`, `event_id`, `jsExecutionTracker`, `buildDate`, etc.) that are not answers. Multiple-choice answers are JSON arrays of strings. Uploaded files appear in two places: `rawRequest["temp_upload"]` maps a `q<number>_...` key to a list of strings of the form `<original filename>#<file server>#<id>`, and the top-level `rawRequest["fileUpload"]` is a list of hosted, percent-encoded URLs for those same files, index-aligned with the `temp_upload` list.

## Current behavior (the bug)

The handler builds the Zulip message purely by splitting the `pretty` string: it splits on `", "` to separate entries and on `":"` to separate each label from its answer. Because Jotform labels and answers may themselves contain commas and colons (e.g. a time field like an appointment time `14:30`, or a label such as `Multiple Choice Question, options:`), these splits land in the wrong places. Entries get fragmented, labels and values are misattributed or truncated, and submissions containing such characters are rendered wrongly or rejected.

## Required behavior

Parsing must no longer rely on naive splitting of `pretty`. The answer values in `rawRequest` are the source of truth; use them to unambiguously recover each entry's boundaries in `pretty` (each entry in `pretty` is `<label>:<known answer text>`, and the known answer text lets you locate where the label ends even when both contain `:` or `,`).

For a submission payload, the integration must post a message where:

1. **Topic** is the form title (`formTitle`).
2. **Body** contains one bullet per answered question, in the order the questions appear in the payload, formatted exactly as `* **<label>**: <answer>`.
3. **Labels and answers are reproduced verbatim**, including any `:`, `,`, or `;` characters they contain. A trailing colon that is part of a label (e.g. `Multiple Choice Question, options:`) is kept.
4. **Multiple-choice / array answers** are rendered as the individual selected values joined by a single space (e.g. `Option; 1 Option2`).
5. **File-upload questions** are rendered after all regular question bullets, separated from them by one blank line. Each uploaded file becomes a Markdown link whose text is the file's original filename (the portion of the `temp_upload` entry before the first `#`) and whose target is the corresponding hosted URL from `fileUpload` (paired by position, URL kept percent-encoded as provided). Multiple files are joined with `", "`. Format: `* **<label>**: [name1](url1), [name2](url2)`.
6. Bookkeeping keys in `rawRequest` (`slug`, `path`, `event_id`, `jsExecutionTracker`, `submitSource`, `buildDate`, `uploadServerUrl`, `eventObserver`, `timeToSubmit`, `validatedNewRequiredFieldIDs`, `file_server`, `fileUpload`, `temp_upload` itself, etc.) must not appear as question bullets — only `q<number>_...` answer fields do.
7. Existing behavior for well-formed simple payloads (no special characters) must be unchanged, and a payload missing the fields needed to build the message must continue to be rejected with the error `Unable to handle Jotform payload`.

## Worked example

Given a submission whose `formTitle` is `Sample testing`, whose `pretty` is:

```
Key1 with colon: and comma, end:Value1 with colon: and comma, end, Same Key:Value 1, Same Key:Value 2, Same Key-Value:Same Key-Value, Value 2:Value 3, Multiple Choice Question, options::Option; 1 Option2, File Upload with colon : and comma , end:error; frontend, UI.png Screenshot_20250331_201054.png
```

and whose `rawRequest` contains (among bookkeeping keys):

```json
{
  "q10_key1With": "Value1 with colon: and comma, end",
  "q11_sameKey": "Value 1",
  "q12_sameKey2": "Value 2",
  "q13_sameKeyValue": "Same Key-Value",
  "q14_value2": "Value 3",
  "q23_multipleChoice": ["Option; 1", "Option2"],
  "temp_upload": {"q22_fileUpload": ["error; frontend, UI.png#jotformfs-e4f4ece4d0a90#01960d74-6a25-7398-87c7-df56ce6711f1", "Screenshot_20250331_201054.png#jotformfs-e4f4ece4d0a90#01960d74-6bbc-7e1b-8187-9028f55b6ef6"]},
  "fileUpload": ["https://www.jotform.com/uploads/kolanuvarun739/243490908500051/6197916587414311452/error%3B%20frontend%2C%20UI.png", "https://www.jotform.com/uploads/kolanuvarun739/243490908500051/6197916587414311452/Screenshot_20250331_201054.png"]
}
```

the posted message must have topic `Sample testing` and body:

```
* **Key1 with colon: and comma, end**: Value1 with colon: and comma, end
* **Same Key**: Value 1
* **Same Key**: Value 2
* **Same Key-Value**: Same Key-Value
* **Value 2**: Value 3
* **Multiple Choice Question, options:**: Option; 1 Option2

* **File Upload with colon : and comma , end**: [error; frontend, UI.png](https://www.jotform.com/uploads/kolanuvarun739/243490908500051/6197916587414311452/error%3B%20frontend%2C%20UI.png), [Screenshot_20250331_201054.png](https://www.jotform.com/uploads/kolanuvarun739/243490908500051/6197916587414311452/Screenshot_20250331_201054.png)
```

Note the duplicate label `Same Key` appearing twice with different values — each answer must produce its own bullet, so the parser cannot treat labels as unique keys.

## Interface requirements

No specific new function, class, or endpoint names are mandated; the change is internal to the Jotform webhook handler, and the observable contract is the message topic/body format described above.
