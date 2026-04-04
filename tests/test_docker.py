"""Tests for Docker image optimization and build efficiency."""
import subprocess
import json
import pytest
import os
from pathlib import Path


class TestDockerOptimization:
    """Verify Docker images are optimized for size and caching."""

    @pytest.mark.skipif(
        not os.path.exists('Dockerfile'),
        reason='Dockerfile not found'
    )
    def test_backend_dockerfile_uses_multistage(self):
        """Backend Dockerfile should use multi-stage build for optimization."""
        dockerfile_path = Path('Dockerfile')
        content = dockerfile_path.read_text()
        # Verify multi-stage build pattern
        assert 'FROM python:3.11-slim AS builder' in content, \
            'Backend Dockerfile must use multi-stage build with builder stage'
        assert 'FROM python:3.11-slim' in content, \
            'Backend Dockerfile must have runtime stage'
        assert '--from=builder' in content, \
            'Runtime stage must copy from builder stage'

    @pytest.mark.skipif(
        not os.path.exists('Dockerfile'),
        reason='Dockerfile not found'
    )
    def test_backend_dockerfile_caches_dependencies(self):
        """Dependencies should be installed before copying source for better caching."""
        dockerfile_path = Path('Dockerfile')
        content = dockerfile_path.read_text()
        lines = content.split('\n')
        # Find builder stage
        builder_start = next(
            (i for i, line in enumerate(lines) if 'AS builder' in line),
            None
        )
        assert builder_start is not None, 'Builder stage not found'
        # Find COPY requirements and COPY source in builder stage
        builder_section = '\n'.join(lines[builder_start:])
        req_copy_idx = builder_section.find('COPY requirements.txt')
        src_copy_idx = builder_section.find('COPY . .')
        assert req_copy_idx != -1, 'requirements.txt must be copied in builder'
        assert src_copy_idx != -1, 'Source code must be copied in builder'
        assert req_copy_idx < src_copy_idx, \
            'requirements.txt must be copied BEFORE source code for layer caching'

    @pytest.mark.skipif(
        not os.path.exists('.dockerignore'),
        reason='.dockerignore not found'
    )
    def test_dockerignore_exists_and_excludes_artifacts(self):
        """Verify .dockerignore exists and excludes build artifacts."""
        dockerignore_path = Path('.dockerignore')
        assert dockerignore_path.exists(), '.dockerignore must exist'
        content = dockerignore_path.read_text()
        # Verify key exclusions for size optimization
        required_exclusions = [
            '__pycache__',
            'node_modules',
            '.git',
            '.pytest_cache',
            '.coverage',
        ]
        for exclusion in required_exclusions:
            assert exclusion in content, \
                f'.dockerignore must exclude {exclusion} to reduce image size'

    @pytest.mark.skipif(
        not os.path.exists('Dockerfile.frontend'),
        reason='Dockerfile.frontend not found'
    )
    def test_frontend_dockerfile_uses_multistage(self):
        """Frontend Dockerfile should use multi-stage build."""
        dockerfile_path = Path('Dockerfile.frontend')
        content = dockerfile_path.read_text()
        assert 'AS builder' in content, \
            'Frontend Dockerfile must use multi-stage build'
        assert '--from=builder' in content, \
            'Frontend runtime stage must copy from builder'

