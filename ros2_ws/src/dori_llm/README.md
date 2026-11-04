# dori_llm

## External LLM (Gemini)

The node uses the `google-genai` SDK (`client.models.generate_content`) with
the current RAG/location context as `system_instruction` and the last three
conversation turns plus the current question as `contents`. The node owns the
history, so `llm/reset` clears the next request's conversation context too.
All conversation, including greetings and thanks, uses the LLM when available.
Destination guidance stays local and only selects registered destinations.

The standard build installs the Gemini SDK from `requirements-runtime.txt`.
From the repository root, install optional RAG/other-provider dependencies:

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_llm/requirements.txt
```

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey).
Set it in the environment of the user/process that starts ROS, then launch from
a built and sourced workspace:

```bash
export GEMINI_API_KEY="your_key_here"
ros2 launch dori_bringup voice.launch.py \
  use_external_llm:=true llm_model:=gemini-3.5-flash-lite
```

`bringup.launch.py` and `hardware.launch.py` accept the same `use_external_llm` and `llm_model`
arguments. For only the LLM node:

```bash
ros2 run dori_llm llm_node --ros-args \
  -p use_external_llm:=true -p model_name:=gemini-3.5-flash-lite
```

Credential precedence is `api_key` (ROS parameter) > `GEMINI_API_KEY` >
`GOOGLE_API_KEY`. DORI explicitly preserves this order even though the SDK's
automatic environment lookup prefers `GOOGLE_API_KEY`. Prefer environment
variables so keys are not passed on the command line. To persist the setting for
interactive Bash sessions, add the export to `~/.bashrc`; services need their own
environment configuration. `.env` files are not loaded automatically, and the
Google Cloud TTS JSON credential is not a Gemini API key. Restart the node after
changing credentials or the model.

`use_external_llm` defaults to `true` in the node and all three launch entrypoints.
To deliberately use only local responses, launch with `use_external_llm:=false`.
On successful initialization the node logs
`Gemini client ready: <model>`; this confirms client creation, not API access.
Missing dependencies/credentials disable the external client, log a warning and
retain local KB responses. API failures or empty model output return a localized
service-unavailable message. Gemini requests have a 20-second HTTP timeout and
one attempt; successful generation logs the model and elapsed time.

Vector retrieval is optional: missing FAISS/embedding dependencies are logged
once per node lifetime and do not prevent Gemini conversation. Restart the node
after installing them or updating the index. Missing structured campus data
does not supply demo opening hours or coordinates to the model.

### Model selection (reviewed 2026-11-05)

The default is `gemini-3.5-flash-lite`. This is a candidate suited to DORI's short,
latency-sensitive campus RAG answers; validate Korean answer quality and latency
on representative campus questions before deployment.

| Model | Role in DORI | Standard paid text pricing per 1M input / output tokens |
| --- | --- | --- |
| `gemini-3.5-flash-lite` | Default; low latency/cost and Google's recommended 2.5 Flash replacement | $0.30 / $2.50 |
| `gemini-3.8-flash` | Compare when more complex reasoning or answer quality warrants the cost | $0.75 / $3.75 through 2026-12-31; $1.50 / $7.50 from 2027-01-01 |
| `gemini-2.5-flash` | Legacy override for existing users; deprecated | $0.30 / $2.50 before migration |

Output pricing includes thinking tokens. Google limits 2.5-model access to users
who actively used them in the past and says 2.5 Flash requests will automatically
route to 3.5 Flash-Lite from 2026-12-01. It is therefore unsuitable as a new-install
default. Model choice is still configurable via the launch/node arguments above.
The Gemini request avoids deprecated sampling parameters and ends in a user turn,
as required by the newer models.

Sources: [deprecation schedule](https://aistudio.google.com/docs/deprecations#gemini-2.5-flash-models),
[3.5 Flash-Lite](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite),
[3.8 Flash](https://aistudio.google.com/docs/models/gemini-3.8-flash),
[pricing](https://aistudio.google.com/docs/pricing),
[migration notes](https://aistudio.google.com/docs/whats-new-gemini-3.6#api-changes-and-parameter-updates).

## build_index.py

Index builder for DORI Knowledge Base

### Install Dependencies

pip install sentence-transformers faiss-cpu numpy

### First Build

python3 build_index.py --docs ./data/campus/processed --output ./rag_index

### Quick update after adding diet file

python3 build_index.py --docs ./data/campus/processed --output ./rag_index --incremental

### Low-memory (Jetson) recommended build

python3 build_index.py --docs ./data/campus/processed --output ./rag_index --batch-size 8 --chunk-batch-size 256

### Environment variable override

DORI_EMBED_BATCH_SIZE=8 DORI_CHUNK_BATCH_SIZE=256 python3 build_index.py --docs ./data/campus/processed --output ./rag_index --incremental
