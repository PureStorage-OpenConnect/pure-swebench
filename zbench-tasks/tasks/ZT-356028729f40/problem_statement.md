# Remove the grey box around most image previews; special-case tiny thumbnails

## Background

Zulip's web client renders inline image previews for uploaded images in messages. Historically, each preview was displayed inside a grey background box sized to the full thumbnail area. This padding existed to prevent the message feed from shifting as images loaded, back when the client did not know an image's dimensions ahead of time.

That constraint no longer holds: the server now embeds each image's original dimensions in the rendered message HTML via a `data-original-dimensions` attribute on the `<img>` element (formatted as `"<width>x<height>"`, in pixels), and the client already uses this to set explicit `width`/`height` attributes and an orientation class (`portrait-thumbnail` or `landscape-thumbnail`) when it post-processes rendered message content before display.

## Required behavior

1. **Drop the grey box for ordinary previews.** Image previews should no longer be padded out to the full thumbnail box with a grey background. The preview's visual footprint should match the image itself. Since dimensions are known before load, this must not reintroduce layout shift.

2. **Special-case very small ("dinky") images.** Images whose natural size is tiny would leave an uncomfortably small click target if rendered at natural size alone. These need distinct treatment:
   - **Definition:** an image is "dinky" when *both* of its original dimensions (read from the existing `data-original-dimensions` attribute) are less than or equal to the thumbnail box size, which is 10em at the user's configured font size — i.e., 10 × the user's existing `web_font_size_px` setting. The comparison is inclusive (a dimension exactly equal to the threshold still counts as dinky). At the default 16px font size, the threshold is 160×160 px.
   - **Classification happens during the client-side post-processing of rendered message HTML**, alongside the existing logic that sets `width`/`height` and the orientation class.
   - **Styling hook:** the `<img>` element of a dinky thumbnail must carry the CSS class `dinky-thumbnail`, *in addition to* everything it gets today: the existing media image class, the orientation class (`portrait-thumbnail`/`landscape-thumbnail`), `width`/`height` attributes taken from the original dimensions, and lazy loading. Non-dinky images must not get this class.
   - **Smaller thumbnail variant:** dinky thumbnails should be fetched at the smallest thumbnail resolution the server generates. Where the server-rendered HTML points the image `src` at the default `840x560.webp` thumbnail variant of the upload, post-processing must rewrite the `src` for a dinky image to the `300x200.webp` variant of the same upload path. For example, `src="/user_uploads/thumbnail/path/to/image.png/840x560.webp"` becomes `src="/user_uploads/thumbnail/path/to/image.png/300x200.webp"`.
   - **Click target:** styling for dinky thumbnails should pad the clickable preview area out to a comfortable minimum (on the order of at least 20px in each dimension), with a background so the target is visible — this is where the grey-box treatment survives.

3. **Everything else is unchanged.** The existing post-processing behavior (anchor gets `target="_blank"`, `rel="noopener noreferrer"`, the media anchor class, and an `aria-label` from the title; images without dimension data are left without width/height; animated-image handling) must be preserved.

### Worked example

Given server-rendered message HTML containing:

```html
<div class="message_inline_image">
  <a href="/user_uploads/path/to/image.png" title="image.png">
    <img data-original-dimensions="1x10" src="/user_uploads/thumbnail/path/to/image.png/840x560.webp">
  </a>
</div>
```

with the user's `web_font_size_px` set to 16, the post-processed output must be an image with classes `media-image-element dinky-thumbnail portrait-thumbnail`, attributes `width="1" height="10" loading="lazy"`, and `src="/user_uploads/thumbnail/path/to/image.png/300x200.webp"`, inside the usual processed anchor (`target="_blank" rel="noopener noreferrer" class="media-anchor-element" aria-label="image.png"`).

Note that the post-processing code must be able to read `web_font_size_px` from the user settings module, so ensure it tolerates that setting being present and uses it for the threshold computation.

## Interface requirements

- Images in message content whose original dimensions (taken from the existing `data-original-dimensions` attribute, in pixels) are both less than or equal to the 10em thumbnail box at the user's configured font size (10 × the existing `web_font_size_px` user setting; comparison is inclusive) are considered "dinky" thumbnails.
- The rendered `<img>` element for a dinky thumbnail gains the CSS class `dinky-thumbnail`, in addition to the existing orientation class (`portrait-thumbnail`/`landscape-thumbnail`) and other pre-existing attributes (width/height from original dimensions, lazy loading).
- Dinky thumbnails must be served at the smallest thumbnail resolution: the image `src` uses the `300x200.webp` thumbnail variant of the upload instead of the default `840x560.webp` variant.

## Motivation

Removing the fixed grey box is a prerequisite for offering a user preference for larger image previews, where a fixed-size padded box would be even more visually wasteful.
