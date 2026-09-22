"""Unit tests for central ModelManager capability routing and runtime resolution."""

import unittest
from unittest.mock import MagicMock, patch

from llm.model_manager import ModelManager, ModelCapability, classify_model
from agent.planner import Planner
from capabilities.vision.provider import OllamaVisionProvider


class TestModelRouting(unittest.TestCase):

    def test_classify_model_capabilities(self):
        """Verify model classification rules."""
        # Embedding models
        self.assertIn(ModelCapability.EMBEDDING, classify_model("nomic-embed-text:latest"))
        self.assertNotIn(ModelCapability.REASONING, classify_model("nomic-embed-text:latest"))
        self.assertIn(ModelCapability.EMBEDDING, classify_model("bge-m3"))
        
        # Vision models
        self.assertIn(ModelCapability.VISION, classify_model("moondream:latest"))
        self.assertIn(ModelCapability.VISION, classify_model("llava:7b"))
        self.assertIn(ModelCapability.VISION, classify_model("qwen2-vl:7b"))
        
        # Reasoning models
        self.assertIn(ModelCapability.REASONING, classify_model("qwen2.5-7b-instruct"))
        self.assertIn(ModelCapability.REASONING, classify_model("llama3.1:8b"))

    def test_reasoning_never_selects_embedding_model(self):
        """Verify that embedding models are never selected for reasoning tasks."""
        mock_provider = MagicMock()
        mock_provider.list_models.return_value = ["nomic-embed-text:latest", "bge-large-en"]
        mock_provider.model_name = "nomic-embed-text:latest"

        mgr = ModelManager(provider=mock_provider)
        # No reasoning models available, only embedding models
        # Must NOT choose an embedding model
        resolved = mgr.verify_and_resolve_model(ModelCapability.REASONING)
        self.assertNotIn("embed", resolved.lower())

    def test_vision_model_resolution(self):
        """Verify vision capability resolves to a vision model or fails closed."""
        mock_provider = MagicMock()
        mock_provider.list_models.return_value = [
            "qwen2.5-7b-instruct:latest",
            "moondream:latest",
            "nomic-embed-text:latest"
        ]
        mock_provider.model_name = "qwen2.5-7b-instruct:latest"

        mgr = ModelManager(provider=mock_provider)
        resolved_vision = mgr.verify_and_resolve_model(ModelCapability.VISION)
        self.assertEqual(resolved_vision, "moondream:latest")

    def test_vision_fails_closed_when_no_vision_model_installed(self):
        """Verify vision resolution returns None rather than falling back to text model."""
        mock_provider = MagicMock()
        mock_provider.list_models.return_value = [
            "qwen2.5-7b-instruct:latest",
            "llama3.1:8b"
        ]
        mock_provider.model_name = "qwen2.5-7b-instruct:latest"

        mgr = ModelManager(provider=mock_provider)
        resolved_vision = mgr.verify_and_resolve_model(ModelCapability.VISION)
        self.assertIsNone(resolved_vision)

    def test_planner_runtime_invokes_model_resolution(self):
        """Verify Planner.create_plan actively invokes model_manager.verify_and_resolve_model."""
        with patch("llm.model_manager.model_manager.verify_and_resolve_model") as mock_resolve, \
             patch("capabilities.registry.registry.get_all_schemas", return_value=[]), \
             patch("agent.planner.Planner.provider") as mock_prov:
            mock_prov.generate.return_value = MagicMock(content='{"thought": "test", "plan": []}')
            
            planner = Planner()
            mock_ctx = MagicMock()
            mock_ctx.to_prompt_dict.return_value = {}
            mock_ctx.recent_history = []
            
            planner.create_plan("Test goal", mock_ctx)
            mock_resolve.assert_called_with(ModelCapability.REASONING)

    def test_vision_provider_uses_central_model_manager(self):
        """Verify OllamaVisionProvider delegates model resolution to central ModelManager."""
        with patch("llm.model_manager.model_manager.verify_and_resolve_model", return_value="moondream:latest") as mock_resolve:
            provider = OllamaVisionProvider(preferred_model=None)
            with patch.object(provider, "_get_installed_models", return_value=["moondream:latest"]):
                model = provider._resolve_model()
                self.assertEqual(model, "moondream:latest")
                mock_resolve.assert_called_with(ModelCapability.VISION)


if __name__ == "__main__":
    unittest.main()
