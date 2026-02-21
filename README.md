# CMO

Focused automated marketing app for X3P:
- Blog generation
- LinkedIn/Facebook adaptation
- Instagram captions
- Built-in fact/brand QA gate

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## UI

Single-page minimal wizard:
- Topic
- Audience
- Tone
- Mode: Complete package, Blog only, Social only

Advanced options are optional and collapsed by default.

## Structure

- `app.py` thin Streamlit entrypoint
- `x3p_content_manager/app/` modular app runtime
  - `input_contract.py`
  - `template_guard.py`
  - `pipeline.py`
  - `progress.py`
  - `backend_health.py`
  - `errors.py`
  - `ui_minimal.py`
- `x3p_content_manager/config/agents.yaml` core agents only
- `x3p_content_manager/config/tasks.yaml` core tasks only
- `x3p_content_manager/crew.py` core crews only
- `x3p_content_manager/tools.py` core tools only

## Outputs

- `outputs/` generated markdown/html assets
- `runs/` manifests, snapshots, and logs

## Launcher Assets

Desktop launcher/icon files are in:
- `assets/launcher/`
