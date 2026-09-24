# Downloading models

Open **Models → Download from Hugging Face** and enter a repository, optionally
with a quantization suffix:

```text
prism-ml/Ternary-Bonsai-2-27B-gguf:TQ1_0
```

You can paste the same string with a leading `-hf`. This is an input shorthand;
LlamaPanel downloads files through Hugging Face HTTPS endpoints without launching
llama-server or executing a shell command.

Click **Review files**, select a model if several match, and check the filenames
and total size. **Download** saves it under the Models directory configured in
Settings. The progress panel offers cancellation; navigating to another tab does
not stop the download. The library refreshes after completion. Select the model
and configure a server as usual.

With no quantization suffix, the preview lists available GGUF models instead of
silently choosing a default quantization. Quantization matching is case
insensitive and follows llama.cpp's tag search (tag followed by `.` or `-`).
Thus `TQ1_0` also matches Bonsai's `PTQ1_0` filenames. Review shows the exact
filenames and lets you choose when more than one model matches.
Split GGUF models download as one group, including every numbered part.
If the repository contains separate `mmproj` GGUF files, enable **Download mmproj**.
When several projectors exist, select the file explicitly; the preview includes
its size in the total. If none are found, the checkbox is disabled and hovering
over it explains why. Projector selection is independent of model quantization.
Projectors are stored in a separate subdirectory beside the downloaded model,
and their directory is shown after completion. They do not appear as standalone
model cards. Configure the appropriate `--mmproj` path when starting your server;
downloading a projector does not change existing server configurations.
You can repeat the preview with the checkbox enabled to add a projector to the
same already downloaded model revision without downloading the model again.

Status is fetched once when the Models screen opens and after user actions.
Only active downloads are polled, every five seconds, and only while that
workspace and browser tab are visible. Returning to the screen refreshes status.

## Storage and failures

Completed downloads live in `<models directory>/.hf-models/<model revision id>/`.
The library scans these managed directories as well as existing top-level GGUF
files. Names remain based on filenames; IDs include the managed directory to
distinguish different repositories or revisions with identical filenames.
The download directory is captured when Download is clicked; changing Settings
afterwards does not move an active download.

The preview pins a repository commit. Each file must match the reported size,
SHA-256 and GGUF magic before the completed directory is published to the
library. Partial downloads are never offered as models. Existing downloads of
the same revision are not overwritten. One download can run at a time across
all server tabs.

Cancellation, network errors and normal panel shutdown remove partial files.
An abrupt process termination can leave `.partial-*` directories inside
`.hf-models`; these are ignored by the scanner and can be deleted while the
panel is stopped. Resuming partial files is not supported yet; retry starts
again. Application updates require finishing or cancelling the download first.

Public repositories work without a token. For a private or gated repository,
obtain access on Hugging Face and provide `HF_TOKEN` in the panel process's
environment before starting it. Tokens are sent only to `huggingface.co`, never
to redirected CDN hosts, and are not saved in settings or presets.

Downloading a model does not guarantee that the installed llama-server supports
its architecture or quantization. For example, specialized ternary GGUF formats
may require a compatible llama.cpp build.
