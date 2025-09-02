from typing import List, Optional, Tuple
from llama_index.core.schema import NodeWithScore
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import logging

logger = logging.getLogger(__name__)

class CrossEncoderReranker:
    def __init__(
        self, 
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2", 
        top_k: int = 12, 
        device: Optional[str] = None,
        max_length: int = 512,
        batch_size: int = 16
    ):
        """
        Initialize CrossEncoder Reranker.
        
        Args:
            model_name: HuggingFace model identifier
            top_k: Number of top results to return
            device: Device to run model on (auto-detected if None)
            max_length: Maximum sequence length for tokenization
            batch_size: Batch size for processing queries
        """
        self.top_k = top_k
        self.max_length = max_length
        self.batch_size = batch_size
        self.device = device or self._get_optimal_device()

        logger.info(f"Loading cross-encoder model: {model_name} on {self.device}")
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.model.to(self.device)
            self.model.eval()
            
            # Enable inference optimizations if available
            if torch.cuda.is_available() and hasattr(torch, 'compile'):
                try:
                    self.model = torch.compile(self.model, mode="reduce-overhead")
                except Exception as e:
                    logger.warning(f"Could not compile model: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {e}")
            raise
            
        logger.info(f"Model loaded successfully")

    def _get_optimal_device(self) -> str:
        """Determine the best available device."""
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"

    def _prepare_pairs(self, query: str, nodes: List[NodeWithScore]) -> List[Tuple[str, str]]:
        """Prepare query-document pairs, filtering out empty content."""
        pairs = []
        for node in nodes:
            try:
                content = node.node.get_content()
                if content and content.strip():
                    pairs.append((query, content.strip()))
                else:
                    logger.debug("Skipping node with empty content")
            except Exception as e:
                logger.warning(f"Error getting content from node: {e}")
                continue
        return pairs

    def _score_batch(self, pairs: List[Tuple[str, str]]) -> List[float]:
        """Score a batch of query-document pairs."""
        if not pairs:
            return []

        queries, documents = zip(*pairs)
        
        try:
            with torch.no_grad():
                inputs = self.tokenizer(
                    list(queries),
                    list(documents),
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                    max_length=self.max_length
                ).to(self.device)
                
                outputs = self.model(**inputs)
                scores = outputs.logits.squeeze(-1)
                
                # Handle single sample case
                if scores.dim() == 0:
                    scores = scores.unsqueeze(0)
                    
                return scores.cpu().tolist()
                
        except Exception as e:
            logger.error(f"Error during batch scoring: {e}")
            return [0.0] * len(pairs)

    def rerank(self, query: str, nodes: List[NodeWithScore]) -> List[NodeWithScore]:
        """
        Re-rank retrieved nodes and return top_k results.
        
        Maintains retrieval pool expansion: expands to max(top_k * 2, 16) 
        before applying cross-encoder reranker.
        
        Args:
            query: Search query string
            nodes: List of retrieved nodes with scores
            
        Returns:
            List of reranked nodes (top_k results)
        """
        if not nodes:
            logger.warning("No nodes provided for reranking")
            return []
            
        if not query or not query.strip():
            logger.warning("Empty query provided, returning original nodes")
            return nodes[:self.top_k]

        # Apply retrieval pool expansion: max(top_k * 2, 16)
        expansion_size = max(self.top_k * 2, 16)
        nodes_to_rerank = nodes[:expansion_size]
        
        logger.debug(f"Reranking {len(nodes_to_rerank)} nodes (expanded from top_k={self.top_k})")

        # Prepare query-document pairs
        pairs = self._prepare_pairs(query.strip(), nodes_to_rerank)
        
        if not pairs:
            logger.warning("No valid pairs created for reranking")
            return nodes_to_rerank[:self.top_k]

        # Score pairs in batches for memory efficiency
        all_scores = []
        for i in range(0, len(pairs), self.batch_size):
            batch_pairs = pairs[i:i + self.batch_size]
            batch_scores = self._score_batch(batch_pairs)
            all_scores.extend(batch_scores)

        # Ensure we have scores for all valid nodes
        valid_nodes = nodes_to_rerank[:len(pairs)]  # Only nodes with valid content
        
        if len(all_scores) != len(valid_nodes):
            logger.warning(f"Score count mismatch: {len(all_scores)} scores for {len(valid_nodes)} nodes")
            # Truncate or pad scores to match nodes
            if len(all_scores) > len(valid_nodes):
                all_scores = all_scores[:len(valid_nodes)]
            else:
                all_scores.extend([0.0] * (len(valid_nodes) - len(all_scores)))

        # Pair nodes with scores and sort by relevance (highest first)
        scored_nodes = list(zip(valid_nodes, all_scores))
        ranked_nodes = sorted(scored_nodes, key=lambda x: x[1], reverse=True)
        
        # Return top_k reranked results
        result = [node for node, _ in ranked_nodes[:self.top_k]]
        
        logger.debug(f"Reranking complete: returned {len(result)} nodes with scores: {[score for _, score in ranked_nodes[:self.top_k]]}")
        return result

    def __del__(self):
        """Cleanup GPU memory on deletion."""
        if hasattr(self, 'model') and hasattr(self, 'device') and 'cuda' in str(self.device):
            try:
                del self.model
                torch.cuda.empty_cache()
            except Exception:
                pass