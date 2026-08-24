import contextlib
import contextvars
import json

from typing import TYPE_CHECKING, Any

import yaml

from backend.core.conf import settings
from backend.core.path_conf import LOCALE_DIR

if TYPE_CHECKING:
    from collections.abc import Iterator

# Context-local current language. Defaults to the configured language so every
# async task/request inherits it; ``I18n.current_language`` reads and writes it
# through property getters/setters, preserving the pre-existing read/write API
# while giving each async context its own isolated locale value.
_current_language: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_language", default=settings.I18N_DEFAULT_LANGUAGE
)


class I18n:
    """Internationalization manager"""

    def __init__(self) -> None:
        self.locales: dict[str, dict[str, Any]] = {}
        self.load_locales()

    @property
    def current_language(self) -> str:
        return _current_language.get()

    @current_language.setter
    def current_language(self, value: str) -> None:
        # NOTE: Assigning via property setter discards the ContextVar reset token.
        # For temporary locale pinning in blocks, prefer using i18n.use_language(lang).
        _current_language.set(value)

    @contextlib.contextmanager
    def use_language(self, value: str) -> Iterator[None]:
        """Temporarily set the current language for the duration of the block.

        Uses ContextVar tokens to set and reset the value cleanly, avoiding
        accumulating state changes on the ContextVar stack.
        """
        token = _current_language.set(value)
        try:
            yield
        finally:
            _current_language.reset(token)

    def load_locales(self) -> None:
        """Load language text"""
        lang_files: list[Any] = []
        for ext in ["*.json", "*.yaml", "*.yml"]:
            lang_files.extend(LOCALE_DIR.glob(ext))

        for lang_file in lang_files:
            with open(lang_file, encoding="utf-8") as f:
                lang = lang_file.stem
                file_type = lang_file.suffix[1:]
                match file_type:
                    case "json":
                        self.locales[lang] = json.loads(f.read())
                    case "yaml" | "yml":
                        self.locales[lang] = yaml.safe_load(f.read())

    def t(self, key: str, default: Any | None = None, **kwargs) -> Any:
        """
        Translation function

        :param key: Target text key, supports dot separation, for example 'response.success'
        :param default: Default text when target language text does not exist
        :param kwargs: Variable parameters in target text
        :return:
        """
        keys = key.split(".")

        translation: Any
        try:
            translation = self.locales[self.current_language]
        except KeyError:
            keys = "error.language_not_found".split(".")
            translation = self.locales[settings.I18N_DEFAULT_LANGUAGE]

        for k in keys:
            if isinstance(translation, dict) and k in translation:
                translation = translation[k]
            else:
                # Pydantic compatibility
                translation = None if keys[0] == "pydantic" else key

        if translation and kwargs:
            translation = translation.format(**kwargs)

        return translation or default


# Create i18n singleton
i18n = I18n()

# Create translation function instance
t = i18n.t
