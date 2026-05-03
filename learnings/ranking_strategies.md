# Ranking Strategies — From Basics to Production

> Personal learning notes on how search and ranking systems work.
> Context: built while designing the job ranking pipeline for Dossier.
> Covers everything from hand-coded rules to production-grade ML ranking.

---

## Why Ranking Matters

Every search system solves the same problem:
given a **query** (user intent) and a **corpus** (all possible results),
return the most relevant items in the best order.

The naive approach — scan everything, score everything — breaks at scale.
Production systems solve this with a **multi-stage funnel**: fast and approximate early,
slow and accurate late. Only the best models see the best candidates.

---

## The Mental Model: Always a Funnel

```
All Candidates (millions)
         │
         ▼  Stage 1 — Candidate Generation    fast, high RECALL
    Top 1,000  ← inverted index + ANN vector search
         │
         ▼  Stage 2 — Coarse Ranking           medium accuracy
    Top 100    ← lightweight ML model, simple features
         │
         ▼  Stage 3 — Fine Ranking / Rerank    high accuracy, slow
    Top 20     ← cross-encoder, LLM, or heavy neural model
         │
         ▼  Stage 4 — Post-Ranking Rules       business constraints
    Final 10   ← diversity cap, freshness boost, ads, personalization
```

No production system uses its best model on all candidates.
The funnel exists because accuracy and speed trade off — you buy speed early, accuracy late.

---

## Strategy 1 — Rule-Based Scoring

### What it is
Hard-coded if/else logic. No ML. No training data needed.

```python
score = 0
if "Senior" in title:     score = 3   # hard cap
if company == "Google":   score += 4
if "service company":     score = min(score, 2)
```

### When to use
- Hard constraints that must never be violated ("never show Senior roles")
- Business rules ("always boost sponsored listings")
- As pre-filters before any ML stage — saves compute

### Strengths
- Fully interpretable — you can explain every decision
- Zero training data needed
- Extremely fast

### Weaknesses
- Brittle: every edge case requires a new rule
- Doesn't generalise: "Sr. Engineer" slips through if you only check "Senior"
- Maintenance burden grows as rules pile up

### Real-world use
- Dossier: seniority hard cap + service company hard-no filter
- E-commerce: "never show out-of-stock items in top 3"
- Content moderation: keyword blocklists

---

## Strategy 2 — TF-IDF and BM25

### What it is
Score documents by how often query terms appear, weighted by how rare each term is across the whole corpus.

**TF (Term Frequency):** how often the word appears in this document  
**IDF (Inverse Document Frequency):** log(total docs / docs containing the word) — rare words score higher  
**BM25:** improved formula that adds document length normalisation and term saturation

```
BM25(q, d) = Σ IDF(t) × [ tf(t,d) × (k1+1) ] / [ tf(t,d) + k1×(1 - b + b×|d|/avgdl) ]
```

You don't need to memorise the formula. The intuition: a rare word appearing once in a short document matters more than a common word appearing 10 times in a very long document.

### When to use
- First-stage retrieval when you need exact keyword match
- Any time "Python 3.11" or "IIIT SriCity" must match exactly (embeddings handle this poorly)
- As one feature in a hybrid ranking model

### Strengths
- Built on an inverted index — sub-millisecond for millions of documents
- Exact match: if the user types a product code, it will find it
- No training data, fully interpretable

### Weaknesses
- Zero semantic understanding: "ML Engineer" and "Machine Learning Engineer" are different
- No understanding of synonyms, paraphrases, or context
- Query terms must appear literally in the document

### Real-world use
- Elasticsearch / Lucene: the default ranking model
- Naukri, LinkedIn early search, Stack Overflow search
- Swiggy restaurant name + dish name search
- Academic literature search

---

## Strategy 3 — Vector Similarity / Dense Retrieval

### What it is
Represent both query and documents as dense vectors (embeddings) in a shared semantic space.
Rank by cosine similarity or dot product.

```
query vector   = embed("LLM engineer with RAG experience")
doc vector     = embed("Foundation model developer, retrieval-augmented generation")
score          = cosine_similarity(query_vec, doc_vec)   # high, even with no word overlap
```

### How embeddings are created
A neural model (BERT, sentence-transformers, OpenAI text-embedding-3) is trained to map
semantically similar text to nearby vectors. "Car" and "automobile" land close. "Car" and "pizza" are far apart.

### Approximate Nearest Neighbor (ANN)
With 1M documents, computing exact cosine similarity is too slow. ANN indexes (FAISS, Annoy, HNSW)
build a structure that finds the ~nearest vectors very fast — trading a small accuracy loss for massive speed gains.

### When to use
- Semantic search: user searches "fast food" → find "pizza", "burger", "fries"
- When synonyms and paraphrases matter: "GenAI" ↔ "Generative AI" ↔ "Foundation Models"
- When exact keyword match is not the primary signal

### Strengths
- Captures meaning, not just surface form
- Handles vocabulary mismatch well
- Scales to millions of documents with ANN

### Weaknesses
- Exact keyword match is weak: "Python 3.11" and "Python 2.7" look very similar
- Embedding quality depends heavily on the model used
- Black box — hard to explain why something ranked high

### Hybrid Search
Combine BM25 + vector similarity. This is the current best practice for production search.
- BM25 handles exact match (product codes, proper nouns, version numbers)
- Vector handles semantics
- Final score = α × BM25 + (1-α) × vector_sim

**Used by:** Modern Elasticsearch (8.x), Pinecone hybrid, Weaviate, Azure AI Search

### Real-world use
- LinkedIn job search (FAISS on skill/title/company embeddings)
- Swiggy semantic dish search ("something spicy" → finds chilli dishes)
- Google's neural matching layer (overlaid on PageRank + BM25)
- Modern ATS systems (Greenhouse, Lever)

---

## Strategy 4 — Learning to Rank (LTR)

### What it is
Train a supervised ML model to predict the relevance of a (query, document) pair,
using a set of hand-engineered features. The model learns which features matter most for your specific use case.

### Feature examples for Dossier
```
- bm25_score                  # keyword overlap between profile and JD
- embedding_similarity        # semantic match
- company_tier                # 1=MAANG, 2=top startup, 3=other, 4=service
- seniority_mismatch_flag     # 1 if title has Senior/Staff/Principal
- required_skills_matched     # count of profile skills in JD
- days_since_posted           # freshness
- jd_length                   # longer JD = more signal, usually
- has_salary_info             # 1/0
```

### Training approaches
- **Pointwise:** Predict absolute relevance score for each document. Simplest, but ignores relative ordering.
- **Pairwise:** Given doc A and doc B for the same query, predict which is more relevant. Treats ranking as classification.
- **Listwise:** Optimise the entire ranked list at once. LambdaMART, LambdaRank. Most accurate.

### Models used
- **LambdaMART** (gradient boosted trees, LightGBM/XGBoost): industry standard for LTR. Used at Bing, Baidu, Airbnb, Booking.com.
- **RankSVM:** older, used less today
- **Neural LTR (DLRM):** Facebook's deep learning recommendation model, used for feed ranking
- **Simple baseline:** Logistic regression on 5-10 features. Surprisingly hard to beat.

### When to use
- When you have labelled data or click/interaction logs
- When you need to combine many signals (freshness, skill match, company quality, urgency)
- When rule-based scoring has hit its ceiling and you need generalisation

### For Dossier: when to build this
After 3+ months of using Dossier and recording:
- Which jobs you applied to (positive signal)
- Which applications got responses (strong positive)
- Which you skipped despite high score (negative signal — the LLM over-scored it)

With 200+ labelled examples, a 5-feature LightGBM LTR model will beat the current LLM scorer for consistency, even if not for accuracy.

### Real-world use
- Bing Search: LambdaMART is the core ranker
- Airbnb: LTR on features like price, availability, host response rate, location
- Booking.com: LTR for hotel ranking
- Swiggy: ML ranker combining rating, delivery time, distance, cuisine match, order history

---

## Strategy 5 — Two-Tower / Bi-Encoder (Recommendation Systems)

### What it is
Train two separate neural networks:
- **Query tower:** takes query (user profile) as input, outputs a fixed-size vector
- **Document tower:** takes document (job listing) as input, outputs a fixed-size vector
- **Score:** dot product or cosine similarity between the two towers' outputs

```
user_embedding  = user_tower(profile_features)      # computed at query time
job_embedding   = job_tower(job_features)            # precomputed offline for all jobs
score           = dot(user_embedding, job_embedding)
```

### Why two towers?
You can precompute all document embeddings offline and store them in a vector index.
At inference, compute one query embedding and do ANN search. This is what makes it scale to billions.

### Training signal
Trained on **interaction data** — not human labels but actual user behaviour:
- Clicked job = positive pair
- Skipped job (shown but not clicked) = negative pair

With billions of impressions, this signal is enormously powerful.

### When to use
- Recommendation at scale: millions of users, millions of items
- When you have rich interaction history
- When latency matters: precomputed embeddings + ANN = sub-10ms

### Strengths
- Scales to billions
- Learns user taste, not just keyword match
- Improves over time as more interactions accumulate

### Weaknesses
- Needs massive training data (millions of labelled pairs)
- Cold start problem: new users and new documents have no history
- Less accurate than cross-encoder on individual pairs

### Real-world use
- **LinkedIn Jobs:** Your profile = query tower. Job listings = document tower. Trained on billions of clicks.
- **YouTube:** Video recommendations (user → video two-tower)
- **Facebook Feed:** Content ranking
- **Spotify:** Song recommendations

---

## Strategy 6 — Cross-Encoder / Reranker

### What it is
Concatenate query and document together and run a neural model (usually BERT-based) with **full attention** between all query tokens and all document tokens. Much more accurate than bi-encoder because the model sees relationships between query and document directly.

```
Input:  [CLS] [your profile] [SEP] [job description] [SEP]
Model:  BERT / RoBERTa / T5
Output: relevance score 0-1
```

### Why more accurate
Bi-encoder: query and document are encoded independently — the representations can't "see" each other.  
Cross-encoder: every query token can attend to every document token — richer, more nuanced matching.

### The cost
You can't precompute document representations (they depend on the query).
Every (query, doc) pair requires a full forward pass. Slow. Expensive.
Used **only** as a second-stage reranker after fast candidate generation.

### When to use
- Reranking top-50 to top-10 after fast BM25 or ANN retrieval
- When accuracy matters more than latency (offline ranking, not real-time)
- As evaluation/label generation for LTR model training

### Models
- BERT-based: `cross-encoder/ms-marco-MiniLM-L-6-v2` (open source, good for job-profile matching)
- Cohere Rerank API (commercial, very good)
- Jina Reranker
- **LLMs (GPT-4, Claude):** The most powerful cross-encoders available. Extremely accurate, extremely slow. What Dossier uses today.

### Real-world use
- Google: BERT as second-stage reranker (announced 2019 — "the biggest leap in 5 years")
- Bing: Cross-encoder over top-100 BM25 results
- Cohere: `rerank` endpoint used by enterprise search
- Dossier: GPT as cross-encoder over all scraped jobs (fine for low volume)

---

## Strategy 7 — LLM-as-Ranker (What Dossier Does Today)

### What it is
Use a large language model to score or rank candidates by providing context (query + document)
in the prompt and asking for an explicit score or ranking.

Two main patterns:
1. **Pointwise:** "Score this job 1-10 given this profile. Return JSON."
2. **Listwise:** "Given this profile, rank these 10 jobs from most to least relevant."

### Strengths
- Zero training data — works out of the box
- Handles nuanced requirements naturally (seniority, domain, salary inference)
- Can generate explanations (reason field)
- Most accurate for individual pair scoring at low volume

### Weaknesses
- Slow: 1-3s per job
- Expensive: ~$0.01 per scoring call at scale
- Inconsistent: same job scored differently across runs
- Doesn't use signals beyond the text (no click data, no freshness, no network)

### When it makes sense
Volume < 500 jobs per run, human-in-the-loop review, early product stage. Exactly where Dossier is now.

### Upgrade path
When volume grows:
1. Use LLM to **generate training labels** (score 1000 jobs once)
2. Extract structured features from those jobs
3. Train a lightweight LTR model on the features + LLM labels
4. Replace LLM scorer with LTR model (100x faster, consistent, cheap)
5. Use LLM only for top-20 reranking

---

## How Google Search Works (Full Stack)

```
User query: "machine learning jobs bangalore"
       │
       ▼  Indexing (offline, continuous)
       Inverted index over 100B+ web pages (Caffeine/Colossus)
       BERT-based embeddings precomputed for all pages
       PageRank scores precomputed for all pages
       │
       ▼  Stage 1 — Retrieval (< 50ms)
       BM25 over inverted index → top 10,000 candidates
       ANN over embedding index → top 10,000 semantic candidates
       Union + dedup → ~20,000 candidates
       │
       ▼  Stage 2 — Coarse Ranking (< 100ms)
       Fast ML model: PageRank + BM25 + freshness + authority signals
       → top 500
       │
       ▼  Stage 3 — Neural Reranking (< 200ms)
       BERT-based model (MUM): deep semantic understanding
       Quality signals: E-E-A-T (expertise, authoritativeness, trustworthiness)
       → top 30
       │
       ▼  Stage 4 — Post-Ranking
       Ads injection (separate auction)
       SafeSearch filtering
       Diversity (not 10 results from same domain)
       Featured snippet extraction
       → Final 10 blue links
```

**Key insight:** Google runs 4 different models in sequence. The expensive model (BERT) never sees more than 500 candidates. It's all about the funnel.

---

## How Swiggy Food Search Works

```
User types: "biryani"
       │
       ▼  Stage 1 — Candidate Generation
       BM25 on dish name + restaurant name: finds all "biryani" dishes
       Vector search: finds "chicken rice", "one pot rice" (semantic match)
       Filter: only restaurants open now, delivering to your pin code
       → ~500 candidates
       │
       ▼  Stage 2 — ML Ranking
       Features:
         - keyword/semantic match score
         - restaurant rating + number of reviews
         - delivery time estimate (your location)
         - your personal order history (ordered from this restaurant before?)
         - dish-level popularity (how often ordered for this query)
         - restaurant acceptance rate (likely to confirm the order)
         - business rules: new restaurant boost, partner tier
       LightGBM model trained on order completions
       → top 50
       │
       ▼  Stage 3 — Post-Ranking
       Sponsored restaurants (injected at fixed positions)
       Diversity: not all biryanis from same restaurant chain
       "Trending in your area" boost
       → Final feed
```

**Key difference from Google:** Swiggy optimises for **order completion** (business metric), not just relevance. A highly relevant restaurant that frequently rejects orders ranks lower. The ranking model is trained on **conversion**, not just clicks.

---

## How LinkedIn Jobs Ranking Works (Most Relevant for Dossier)

```
Your profile (skills, experience, education, connections)
       │
       ▼  Offline — Embedding Generation
       Two-tower model encodes your profile → user embedding
       Same model encodes every job listing → job embedding
       All job embeddings stored in FAISS index
       │
       ▼  Stage 1 — ANN Retrieval (your query time)
       user_embedding → ANN search → top 500 semantically similar jobs
       │
       ▼  Stage 2 — LTR Reranking
       Features per (you, job) pair:
         - embedding similarity score
         - connection signal: does someone you know work there?
         - company follow signal: do you follow this company?
         - seniority match: does the required exp match yours?
         - apply rate: how often do people like you apply to this job?
         - freshness: hours since posted
         - Easy Apply available?
       LambdaMART model trained on billions of apply/click signals
       → top 20
       │
       ▼  Stage 3 — Post-Ranking
       "Open to Work" boost
       InMail/Premium placement
       Saved job boost
       → Your feed
```

**Why your logged-in feed is better than guest API:** The connection signal + apply rate signals are trained on your graph. Guest API has none of this. It's pure BM25 + basic embedding — Stage 1 only, no Stage 2.

---

## Dossier — Current State and Evolution Path

### Today (Phase A)
```
Fetch (Indeed + LinkedIn) → Hard filter (rules) → LLM cross-encoder scoring → Sort by score
```
LLM is doing Stage 3 work on all candidates. Works for < 200 jobs.

### Phase B — Two-Stage (when LinkedIn is working + 10 search terms)
```
Fetch ~300 raw → Hard filter → Embedding similarity filter (top 80) → LLM scoring (top 80)
```
Add `sentence-transformers` to embed your profile + each JD, pre-filter to top 80 by cosine similarity,
then LLM only scores those 80. Faster + cheaper.

### Phase C — Feature-Engineered Consistent Scoring
Extract structured features *before* LLM scoring:
```python
features = {
    "company_tier":          classify_company(company_name),     # rule-based lookup
    "seniority_in_title":    detect_seniority(title),            # regex
    "skills_matched":        count_skill_overlap(jd, profile),   # keyword match
    "days_old":              compute_days_old(date_posted),       # deterministic
    "has_salary":            bool(salary_field),
}
```
Pass these as facts to the LLM scorer. The LLM no longer has to *infer* company tier from
an Amazon job title — it's told. Reduces inconsistency by ~60%.

### Phase D — LTR (after 3+ months of data)
```python
# Training signal: jobs applied to + response rate
X = feature_matrix(all_scored_jobs)   # 8 features per job
y = applied_and_got_response          # 1/0 label
model = LGBMRanker().fit(X, y)
```
Replace LLM scorer with 1ms LightGBM inference. Use LLM only for top-10 reranking.

---

## Interview Relevance

All of this is core **ML Engineering / Applied ML** work. It maps directly to:

| What was built | Interview topic it covers |
|---|---|
| Multi-source job fetching with dedup | Data pipeline design, ETL |
| BM25 vs embedding vs LLM scoring | Information retrieval fundamentals |
| Two-stage retrieval pipeline | System design: ML serving at scale |
| Feature engineering (seniority, company tier, freshness) | Feature engineering for ranking |
| LTR with LightGBM | Supervised ML, gradient boosting |
| Two-tower model architecture | Recommendation systems design |
| LLM-as-cross-encoder | LLM application design patterns |
| Diversity cap, post-ranking rules | Business-aware ML systems |

Companies that ask about ranking in interviews: **Google (ML SWE)**, **LinkedIn (MLE)**, **Amazon (Applied Scientist)**, **Swiggy/Zepto/Meesho (ML Platform)**, **Flipkart (Search/Reco)**.

The standard ML system design questions are:
- "Design YouTube recommendations"
- "Design a job search system"
- "Design a feed ranking system"

All of them map exactly to this funnel. If you can explain the funnel, explain why each stage
exists (speed vs accuracy tradeoff), name the models at each stage, and discuss training signal —
that's a senior-level answer at any product company.

---

## Key Papers to Know (Reference)

- **BM25:** Robertson et al., 1994 — "The Probabilistic Relevance Framework: BM25 and Beyond"
- **Word2Vec:** Mikolov et al., 2013 — the origin of dense embeddings
- **BERT for IR:** Devlin et al., 2018 + Nogueira & Cho 2019 (BERT as reranker)
- **LambdaMART:** Burges, 2010 — the LTR algorithm behind most production rankers
- **Two-Tower:** Yi et al., 2019 — "Sampling-Bias-Corrected Neural Modeling for Large Corpus Item Recommendations" (YouTube/Google)
- **FAISS:** Johnson et al., 2017 — "Billion-scale similarity search with GPUs"

---

*Last updated: 2026-05-02 | Context: Dossier job search agent, Phase A*
