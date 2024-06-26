from abc import ABC, abstractmethod
from typing import Annotated, Type, Any, Dict, Union, Callable, Optional, Sequence, List

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.prompt_values import ChatPromptValue
from langchain_core.runnables import RunnableConfig, Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import _rm_titles, convert_to_openai_function, convert_to_openai_tool  # noqa
from langchain_core.utils.json_schema import dereference_refs
from pydantic import ValidationError, PlainValidator, BaseModel as BaseModelV2, BaseModel
from pydantic.v1 import BaseModel as BaseModelV1, parse_obj_as


def validated(value: BaseModelV1, target_class: Type[Any]) -> BaseModelV1:
    try:
        return parse_obj_as(target_class, value)  # noqa
    except ValidationError as e:
        raise ValidationError(f"Input of invalid type: {e}")


def pydantic_v1_port(cls):
    return Annotated[cls, PlainValidator(lambda val: validated(val, cls))]


def convert_pydantic_to_openai_function_v2(
        model: Type[BaseModelV2],
) -> Dict[str, Any]:
    schema = dereference_refs(model.model_json_schema())
    schema.pop("definitions", None)
    title = schema.pop("title", "")
    default_description = schema.pop("description", "")
    return {
        "name": title,
        "description": default_description,
        "parameters": _rm_titles(schema)
    }


def convert_to_openai_function_v2(
        function: Union[Dict[str, Any], Type[BaseModelV1], Callable, BaseTool, Type[BaseModelV2]],
) -> Dict[str, Any]:
    if isinstance(function, type) and issubclass(function, BaseModelV2):
        return convert_pydantic_to_openai_function_v2(function)
    else:
        return convert_to_openai_function(function)


def convert_to_openai_tool_v2(
        tool: Union[Dict[str, Any], Type[BaseModelV1], Callable, BaseTool, Type[BaseModelV2]],
) -> Dict[str, Any]:
    if isinstance(tool, type) and issubclass(tool, BaseModelV2):
        return convert_to_openai_tool(
            convert_to_openai_function_v2(tool)
        )
    else:
        return convert_to_openai_tool(tool)


class ChatPromptValue2DictAdapter(Runnable[Union[ChatPromptValue, Dict], Dict[str, Sequence[BaseMessage]]]):
    def invoke(
            self, input: Union[ChatPromptValue, Dict], config: Optional[RunnableConfig] = None  # noqa
    ) -> Dict[str, Sequence[BaseMessage]]:
        if isinstance(input, Dict):
            return input
        return {
            "messages": input.messages
        }


class ContextSizeLimiter(BaseModel, ABC):
    max_context_size: int
    llm: pydantic_v1_port(BaseChatModel)

    @abstractmethod
    def limit_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        pass


class NaiveContextSizeLimiter(ContextSizeLimiter):
    def limit_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        num_messages_to_keep = 1
        while num_messages_to_keep <= len(messages):
            extended_num_messages_to_keep = num_messages_to_keep + 1
            last_messages = messages[-extended_num_messages_to_keep:]
            tokens_in_extended_messages = self.llm.get_num_tokens_from_messages(last_messages)
            if tokens_in_extended_messages > self.max_context_size:
                break
            num_messages_to_keep = extended_num_messages_to_keep
        return messages[-num_messages_to_keep:]
