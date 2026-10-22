## Email integration: long subject lines are silently truncated

### Observed behavior

Zulip's incoming email integration (the email gateway) uses the email's subject line as the topic of the resulting Zulip message. Zulip topics have a 60-character length limit, so when an incoming email has a subject longer than 60 characters, the subject is cropped to fit. The portion of the subject beyond the limit is lost entirely — it does not appear anywhere in the resulting Zulip message.

### Expected behavior

When an incoming email's subject is too long to fit in the topic (i.e., it gets truncated to satisfy the 60-character topic limit), the full subject should be preserved in the message body. Specifically, add a line of the form:

```
Subject: {full subject}
```

to the message content. If the message body already begins with a sender line (the gateway can prepend one indicating who the email is from), the subject line should be placed just below that sender line; otherwise it should be the first line at the top of the message.

### Design notes

- The simplest option is to include the `Subject: {full subject}` line on every message whose subject was truncated, rather than only on the first message in a given topic. This handles the case where multiple distinct long subjects abbreviate to the same truncated topic. (An alternative considered was to add it only for the first message with that topic, or the first within some recent time window such as a week, but always including it when truncation occurred is acceptable and avoids that complexity.)
- Messages whose subjects fit within the topic length limit should be unaffected.
