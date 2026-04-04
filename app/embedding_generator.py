"""DINOv2 ViT-L14 embedding generator for image feature extraction."""
import torch
import torch.nn.functional as F
from typing import List, Tuple, Dict
from PIL import Image
import io
import numpy as np


class EmbeddingGenerator:
    """Generate 1024-dimensional embeddings using DINOv2 ViT-L14 model."""
    
    def __init__(self, device: str = None):
        """Initialize DINOv2 model for embedding generation.
        
        Args:
            device: torch device ('cuda', 'cpu', or None for auto-detection)
        """
        # Auto-detect device if not specified
        if device is None:
            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        else:
            self.device = device
        
        # Load DINOv2 ViT-L14 model (outputs 1024-dim vectors)
        self.model = torch.hub.load('facebookresearch/dinov2', 'dinov2_vitl14')
        self.model = self.model.to(self.device)
        self.model.eval()  # Set to evaluation mode
        
        # Store model metadata
        self.model_name = 'dinov2_vitl14'
        self.embedding_dim = 1024
    
    def _preprocess_image(self, image_data: bytes) -> torch.Tensor:
        """Convert image bytes to normalized tensor for model input.
        
        Args:
            image_data: Raw image bytes
        
        Returns:
            Preprocessed image tensor (1, 3, 518, 518)
        """
        # Load image from bytes
        image = Image.open(io.BytesIO(image_data)).convert('RGB')
        
        # Resize to 518x518 (DINOv2 standard input size)
        image = image.resize((518, 518), Image.Resampling.BICUBIC)
        
        # Convert to tensor and normalize
        image_tensor = torch.from_numpy(np.array(image)).float() / 255.0
        image_tensor = image_tensor.permute(2, 0, 1)  # HWC -> CHW
        
        # Normalize with ImageNet statistics
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        image_tensor = (image_tensor - mean) / std
        
        return image_tensor.unsqueeze(0).to(self.device)  # Add batch dimension
    
    def generate_embedding(self, image_data: bytes) -> Tuple[List[float], float]:
        """Generate embedding for a single image.
        
        Args:
            image_data: Raw image bytes
        
        Returns:
            Tuple of (embedding vector as list, confidence score)
        """
        with torch.no_grad():
            # Preprocess image
            image_tensor = self._preprocess_image(image_data)
            
            # Generate embedding
            embedding = self.model(image_tensor)
            
            # Calculate confidence as the norm of the embedding before normalization
            # (higher norm indicates stronger feature activation)
            confidence = float(torch.norm(embedding, p=2).item())
            
            # Normalize embedding to unit length (L2 normalization)
            embedding = F.normalize(embedding, p=2, dim=1)
            
            # Convert to list and return with confidence
            embedding_list = embedding.squeeze(0).cpu().tolist()
            return embedding_list, confidence
    
    def generate_embeddings_batch(self, image_data_list: List[bytes]) -> List[Tuple[List[float], float]]:
        """Generate embeddings for multiple images in batch.
        
        Args:
            image_data_list: List of raw image bytes
        
        Returns:
            List of tuples (embedding vector as list, confidence score)
        """
        results = []
        
        with torch.no_grad():
            # Process images in batch
            image_tensors = []
            for image_data in image_data_list:
                image_tensor = self._preprocess_image(image_data)
                image_tensors.append(image_tensor)
            
            # Stack all images into single batch tensor
            batch_tensor = torch.cat(image_tensors, dim=0)
            
            # Generate embeddings for entire batch
            embeddings = self.model(batch_tensor)
            
            # Calculate confidence scores (norm before normalization)
            confidences = torch.norm(embeddings, p=2, dim=1)
            
            # Normalize embeddings
            embeddings = F.normalize(embeddings, p=2, dim=1)
            
            # Convert to list format with confidence scores
            for i in range(len(image_data_list)):
                embedding_list = embeddings[i].cpu().tolist()
                confidence = float(confidences[i].item())
                results.append((embedding_list, confidence))
        
        return results
    
    def get_model_info(self) -> Dict[str, any]:
        """Return metadata about the embedding model.
        
        Returns:
            Dictionary with model name and embedding dimension
        """
        return {
            'model_name': self.model_name,
            'embedding_dim': self.embedding_dim,
            'device': self.device
        }

