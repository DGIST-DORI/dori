# dori_llm

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
