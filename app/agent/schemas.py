from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ToolParameter:
    type: str
    description: str
    required: bool = False
    enum: Optional[List[str]] = None

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, ToolParameter]

    def to_json_schema(self) -> Dict[str, Any]:
        properties = {}
        required = []
        for param_name, param in self.parameters.items():
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param_name] = prop
            if param.required:
                required.append(param_name)

        return {
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }

@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None

@dataclass
class ToolExecutionResult:
    tool_name: str
    success: bool
    output: str
    data: Dict[str, Any] = field(default_factory=dict)
