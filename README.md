# LlamaPanel

## About

LlamaPanel is a web panel for managing local `llama-server` instances from
llama.cpp: select GGUF models and LoRA adapters, configure flags, manage presets,
start, stop and restart servers, and view logs. Multiple servers can run at the
same time on different ports.

The panel runs on the machine containing your models and `llama-server` binary.
External clients connect directly to each instance's OpenAI-compatible API.
Detailed documentation and architecture documents are in [docs](docs/README.md).

## Installation and startup

You need **Python 3.12+**, a `llama-server` binary and a GGUF model.
Building from source also requires **Node.js 20+**.

### From a release

Download and extract the ZIP from [Releases](https://github.com/Tosturi/LlamaPanel/releases).
The frontend is already built; Node.js is not required. Open a terminal in the
extracted `LlamaPanel` directory and run:

```bash
python run.py
```

### From source

```bash
git clone https://github.com/Tosturi/LlamaPanel.git
cd LlamaPanel
cd frontend
npm ci
npm run build
cd ..
```

Then run:

```bash
python run.py
```

On the first run, the launcher creates `.venv` and installs backend dependencies.
Open **http://127.0.0.1:8000**, click **Settings** in the header, and choose the
model folder, LoRA folder and `llama-server` executable using **Browse** or by
entering paths. Save settings; no configuration file editing is required.
You can change the panel address and port with
`python run.py --host 0.0.0.0 --port 8000`. The panel and
each `llama-server` instance must use different ports.

On **Servers**, create an instance with its own port. Click **Open server**,
select a model and press **Start**. See the [instance guide](docs/instances.md)
for navigation and quick controls.

After updating the source, run `npm ci` and `npm run build` in `frontend` again,
then restart the panel. Settings, presets, instance configurations and logs are stored separately from the
installation directory; see [configuration and storage](docs/configuration.md).

## License

[MIT](LICENSE).
