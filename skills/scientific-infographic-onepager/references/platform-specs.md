# Platform Specs

## Xiaohongshu / Rednote Single Image

Default sizes:

- `1080 x 1620`: normal dense science onepager.
- `1080 x 1440`: compact social long image.
- `1080 x 1920`: unusually dense educational explainer; use only when the copy remains readable.

Safe area:

- Side margin: 64-88 px.
- Top margin: 64-104 px.
- Bottom margin: 72-120 px.
- Keep titles, module labels, axis labels, caveats, and footer text inside the safe area.

Export:

- PNG for text-heavy images.
- HTML and JSON spec remain editable source files.
- Naming: `onepager.html`, `onepager.png`, `render-report.json`, `check-report.json`.

Preview rule:

- Check the rendered PNG at mobile size. The main claim must be readable without zooming.
- If the first 35% of the image does not communicate the promise, rewrite the title or reorganize the top modules.
