## Compose box prematurely switches to edit mode when sending from preview mode

### Observed behavior

In the Zulip web app, when a user composes a message, switches the compose box to preview mode, and then sends the message, the compose box switches back to edit mode while the message is still being sent — before the send has completed and the compose box has been emptied.

This is easiest to observe when the send takes a noticeable amount of time, for example when sending a large message (such as one with an attachment) with network throttling enabled: as soon as the send is initiated from preview mode, the compose box flips from the rendered preview back to the raw-markdown edit view even though the message content is still present and still in flight.

### Expected behavior

When sending from preview mode, the compose box should remain in preview mode for the duration of the send, and only switch back to edit mode once the send has completed and the compose box has been emptied.

### Reproduction steps

1. Open the compose box and write a large message (e.g., include an attachment); enabling network throttling in the browser's dev tools makes the effect easier to see.
2. Switch the compose box to preview mode.
3. Send the message.
4. Observe that the compose box switches to edit mode immediately, while the message is still sending, rather than waiting until the compose box is empty.
