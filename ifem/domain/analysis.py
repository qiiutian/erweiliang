from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Callable, Mapping, Protocol, runtime_checkable


ProgressReporter = Callable[[float, str], None]


@dataclass(frozen=True)
class AlgorithmMetadata:
    identifier: str
    display_name: str
    version: str
    description: str = ""
    parameter_schema_version: str = "1"

    def __post_init__(self):
        identifier = self.identifier.strip()
        display_name = self.display_name.strip()
        version = self.version.strip()
        if not identifier:
            raise ValueError("算法标识不能为空。")
        if not display_name:
            raise ValueError("算法显示名称不能为空。")
        if not version:
            raise ValueError("算法版本不能为空。")
        parameter_schema_version = self.parameter_schema_version
        if (
            not isinstance(parameter_schema_version, str)
            or not parameter_schema_version.strip()
        ):
            raise ValueError("算法参数模式版本不能为空。")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "version", version)
        object.__setattr__(
            self,
            "parameter_schema_version",
            parameter_schema_version.strip(),
        )


class InputValidationError(ValueError):
    """An input validation failure tied to a stable field path."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(str(message))
        self.field = field


@dataclass(frozen=True)
class AlgorithmCapabilities:
    model_dimensions: tuple[int, ...]
    element_families: tuple[str, ...]
    measurement_types: tuple[str, ...]
    result_fields: tuple[str, ...]
    supports_transient: bool = False
    modeling_spaces: tuple[str, ...] = ("2d", "3d")
    geometry_kinds: tuple[str, ...] = ("line", "circular_arc")
    supports_mixed_geometry: bool = True

    def __post_init__(self):
        dimensions = tuple(sorted({int(value) for value in self.model_dimensions}))
        if not dimensions or any(value not in {1, 2, 3} for value in dimensions):
            raise ValueError("算法模型维度必须由 1、2、3 中的值组成。")
        modeling_spaces = tuple(
            sorted({str(value).strip().lower() for value in self.modeling_spaces})
        )
        if not modeling_spaces or any(value not in {"2d", "3d"} for value in modeling_spaces):
            raise ValueError("算法建模空间必须由 2d、3d 中的值组成。")
        geometry_kinds = tuple(
            sorted({str(value).strip().lower() for value in self.geometry_kinds})
        )
        if not geometry_kinds or any(not value for value in geometry_kinds):
            raise ValueError("算法支持的几何类型不能为空。")
        object.__setattr__(self, "model_dimensions", dimensions)
        object.__setattr__(self, "element_families", tuple(self.element_families))
        object.__setattr__(self, "measurement_types", tuple(self.measurement_types))
        object.__setattr__(self, "result_fields", tuple(self.result_fields))
        object.__setattr__(self, "modeling_spaces", modeling_spaces)
        object.__setattr__(self, "geometry_kinds", geometry_kinds)
        object.__setattr__(
            self,
            "supports_mixed_geometry",
            bool(self.supports_mixed_geometry),
        )


@dataclass(frozen=True)
class ValidationIssue:
    message: str
    field: str | None = None
    severity: str = "error"


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def error_message(self) -> str:
        errors = [issue.message for issue in self.issues if issue.severity == "error"]
        return "\n".join(errors)

    @classmethod
    def valid(cls) -> "ValidationReport":
        return cls()

    @classmethod
    def invalid(cls, message: str, *, field: str | None = None) -> "ValidationReport":
        return cls((ValidationIssue(str(message), field=field),))


@dataclass(frozen=True)
class AnalysisContext:
    project_config: Mapping[str, Any]
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "project_config", dict(self.project_config))
        object.__setattr__(self, "parameters", dict(self.parameters))


@dataclass(frozen=True)
class AnalysisResult:
    algorithm_id: str
    algorithm_version: str
    native_model: Any
    inputs: Mapping[str, Any]
    fields: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "inputs", dict(self.inputs))
        object.__setattr__(self, "fields", dict(self.fields))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class AnalysisCancelled(RuntimeError):
    """Raised when a pending or running analysis is cancelled."""


class CancellationToken:
    def __init__(self):
        self._event = Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self):
        self._event.set()

    def raise_if_cancelled(self):
        if self.is_cancelled:
            raise AnalysisCancelled("分析任务已取消。")


@runtime_checkable
class ReconstructionAlgorithm(Protocol):
    metadata: AlgorithmMetadata
    capabilities: AlgorithmCapabilities

    def parameter_schema(self) -> Mapping[str, Any]: ...

    def validate(self, context: AnalysisContext) -> ValidationReport: ...

    def solve(
        self,
        context: AnalysisContext,
        *,
        progress: ProgressReporter,
        cancellation: CancellationToken,
    ) -> AnalysisResult: ...
