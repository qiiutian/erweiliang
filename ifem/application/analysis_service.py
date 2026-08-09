from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ifem.domain.analysis import (
    AnalysisContext,
    AnalysisResult,
    CancellationToken,
    ProgressReporter,
    ReconstructionAlgorithm,
)


DEFAULT_ALGORITHM_ID = "ifem.beam2d.surface_integral.v1"


class AlgorithmValidationError(ValueError):
    """Raised when project data is incompatible with an algorithm."""


class AlgorithmRegistry:
    def __init__(self, algorithms: Iterable[ReconstructionAlgorithm] = ()):
        self._algorithms: dict[str, ReconstructionAlgorithm] = {}
        for algorithm in algorithms:
            self.register(algorithm)

    def register(self, algorithm: ReconstructionAlgorithm):
        if not isinstance(algorithm, ReconstructionAlgorithm):
            raise TypeError("算法插件未实现 ReconstructionAlgorithm 协议。")
        identifier = algorithm.metadata.identifier
        if identifier in self._algorithms:
            raise ValueError(f"算法标识已注册：{identifier}")
        self._algorithms[identifier] = algorithm

    def get(self, identifier: str) -> ReconstructionAlgorithm:
        try:
            return self._algorithms[str(identifier)]
        except KeyError as exc:
            available = "、".join(self._algorithms) or "无"
            raise KeyError(f"未知算法：{identifier}。可用算法：{available}") from exc

    def list(self) -> tuple[ReconstructionAlgorithm, ...]:
        return tuple(self._algorithms.values())

    def __contains__(self, identifier: object) -> bool:
        return identifier in self._algorithms


def _ignore_progress(_fraction: float, _message: str):
    return None


class AnalysisService:
    def __init__(self, registry: AlgorithmRegistry, *, default_algorithm_id: str):
        if default_algorithm_id not in registry:
            raise KeyError(f"默认算法尚未注册：{default_algorithm_id}")
        self.registry = registry
        self.default_algorithm_id = default_algorithm_id

    def run(
        self,
        project_config: Mapping[str, Any],
        *,
        algorithm_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        progress: ProgressReporter | None = None,
        cancellation: CancellationToken | None = None,
    ) -> AnalysisResult:
        algorithm = self.registry.get(algorithm_id or self.default_algorithm_id)
        context = AnalysisContext(project_config, parameters or {})
        progress = progress or _ignore_progress
        cancellation = cancellation or CancellationToken()

        cancellation.raise_if_cancelled()
        report = algorithm.validate(context)
        if not report.is_valid:
            raise AlgorithmValidationError(report.error_message or "算法输入校验失败。")

        progress(0.0, "输入校验完成")
        cancellation.raise_if_cancelled()
        result = algorithm.solve(
            context,
            progress=progress,
            cancellation=cancellation,
        )
        if result.algorithm_id != algorithm.metadata.identifier:
            raise RuntimeError("算法返回结果的标识与已注册插件不一致。")
        progress(1.0, "计算完成")
        return result


def create_default_analysis_service() -> AnalysisService:
    from ifem.algorithms.beam_surface_integral import BeamSurfaceIntegralAlgorithm

    registry = AlgorithmRegistry((BeamSurfaceIntegralAlgorithm(),))
    return AnalysisService(registry, default_algorithm_id=DEFAULT_ALGORITHM_ID)


_default_service: AnalysisService | None = None


def get_default_analysis_service() -> AnalysisService:
    global _default_service
    if _default_service is None:
        _default_service = create_default_analysis_service()
    return _default_service
