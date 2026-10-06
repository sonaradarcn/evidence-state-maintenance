# Held-out oracle validation

20 static + 10 behaviour facts drawn at random (seed 20261002) from all held-out facts; 5 random commits each (from the 701 HISTORY+s0+FUTURE commits). Each value was recomputed from a real `git worktree` checkout (see validate_h.py docstring for what is independent of the main pass).

**150/150 (fact, commit) values match** (422s).

| fact | type | commit idx | stored | recomputed | match |
|---|---|---|---|---|---|
| poetry-core:T2:8 | T2 | 52 | `False` | `False` | yes |
| poetry-core:T2:8 | T2 | 77 | `False` | `False` | yes |
| poetry-core:T2:8 | T2 | 146 | `False` | `False` | yes |
| poetry-core:T2:8 | T2 | 464 | `NONE` | `NONE` | yes |
| poetry-core:T2:8 | T2 | 638 | `NONE` | `NONE` | yes |
| black:T1:n8 | T1 | 266 | `src/black/strings.py` | `src/black/strings.py` | yes |
| black:T1:n8 | T1 | 333 | `src/black/strings.py` | `src/black/strings.py` | yes |
| black:T1:n8 | T1 | 434 | `src/black/strings.py` | `src/black/strings.py` | yes |
| black:T1:n8 | T1 | 494 | `src/black/strings.py` | `src/black/strings.py` | yes |
| black:T1:n8 | T1 | 606 | `src/black/strings.py` | `src/black/strings.py` | yes |
| mkdocs:T3:n8 | T3 | 191 | `self, use_directory_urls` | `self, use_directory_urls` | yes |
| mkdocs:T3:n8 | T3 | 245 | `self, use_directory_urls` | `self, use_directory_urls` | yes |
| mkdocs:T3:n8 | T3 | 400 | `self, use_directory_urls` | `self, use_directory_urls` | yes |
| mkdocs:T3:n8 | T3 | 406 | `self, use_directory_urls` | `self, use_directory_urls` | yes |
| mkdocs:T3:n8 | T3 | 502 | `self, use_directory_urls` | `self, use_directory_urls` | yes |
| kombu:T5:27 | T5 | 53 | `4` | `4` | yes |
| kombu:T5:27 | T5 | 199 | `4` | `4` | yes |
| kombu:T5:27 | T5 | 232 | `4` | `4` | yes |
| kombu:T5:27 | T5 | 392 | `4` | `4` | yes |
| kombu:T5:27 | T5 | 600 | `4` | `4` | yes |
| scrapy:T4:18 | T4 | 8 | `service_identity>=18.1.0` | `service_identity>=18.1.0` | yes |
| scrapy:T4:18 | T4 | 260 | `service_identity>=23.1.0` | `service_identity>=23.1.0` | yes |
| scrapy:T4:18 | T4 | 356 | `service_identity>=23.1.0` | `service_identity>=23.1.0` | yes |
| scrapy:T4:18 | T4 | 485 | `service_identity>=23.1.0` | `service_identity>=23.1.0` | yes |
| scrapy:T4:18 | T4 | 678 | `service_identity>=24.2.0` | `service_identity>=24.2.0` | yes |
| rich:T3:n32 | T3 | 47 | `NONE` | `NONE` | yes |
| rich:T3:n32 | T3 | 150 | `NONE` | `NONE` | yes |
| rich:T3:n32 | T3 | 355 | `self, handle, progress, task, close_handle` | `self, handle, progress, task, close_handle` | yes |
| rich:T3:n32 | T3 | 411 | `self, handle, progress, task, close_handle` | `self, handle, progress, task, close_handle` | yes |
| rich:T3:n32 | T3 | 587 | `self, handle, progress, task, close_handle` | `self, handle, progress, task, close_handle` | yes |
| werkzeug:T6:34 | T6 | 34 | `src/werkzeug/__init__.py, src/werkzeug/wrappers/base_request` | `src/werkzeug/__init__.py, src/werkzeug/wrappers/base_request` | yes |
| werkzeug:T6:34 | T6 | 202 | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | yes |
| werkzeug:T6:34 | T6 | 242 | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | yes |
| werkzeug:T6:34 | T6 | 273 | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | yes |
| werkzeug:T6:34 | T6 | 555 | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | `src/werkzeug/__init__.py, src/werkzeug/wrappers/request.py, ` | yes |
| pyparsing:T3:n1 | T3 | 300 | `self, expr, stop_on, stopOn` | `self, expr, stop_on, stopOn` | yes |
| pyparsing:T3:n1 | T3 | 346 | `self, expr, stop_on, stopOn` | `self, expr, stop_on, stopOn` | yes |
| pyparsing:T3:n1 | T3 | 419 | `self, expr, stop_on, stopOn` | `self, expr, stop_on, stopOn` | yes |
| pyparsing:T3:n1 | T3 | 571 | `self, expr, stop_on, kwargs` | `self, expr, stop_on, kwargs` | yes |
| pyparsing:T3:n1 | T3 | 654 | `self, expr, stop_on, kwargs` | `self, expr, stop_on, kwargs` | yes |
| marshmallow:T3:n39 | T3 | 189 | `self, messages, field_name, index` | `self, messages, field_name, index` | yes |
| marshmallow:T3:n39 | T3 | 434 | `self, messages, field_name, index` | `self, messages, field_name, index` | yes |
| marshmallow:T3:n39 | T3 | 458 | `self, messages, field_name, index` | `self, messages, field_name, index` | yes |
| marshmallow:T3:n39 | T3 | 484 | `self, messages, field_name, index` | `self, messages, field_name, index` | yes |
| marshmallow:T3:n39 | T3 | 659 | `self, messages, field_name, index` | `self, messages, field_name, index` | yes |
| typer:T2:n30 | T2 | 64 | `None` | `None` | yes |
| typer:T2:n30 | T2 | 78 | `None` | `None` | yes |
| typer:T2:n30 | T2 | 85 | `None` | `None` | yes |
| typer:T2:n30 | T2 | 136 | `None` | `None` | yes |
| typer:T2:n30 | T2 | 650 | `None` | `None` | yes |
| networkx:T2:n39 | T2 | 38 | `None` | `None` | yes |
| networkx:T2:n39 | T2 | 62 | `None` | `None` | yes |
| networkx:T2:n39 | T2 | 130 | `None` | `None` | yes |
| networkx:T2:n39 | T2 | 138 | `None` | `None` | yes |
| networkx:T2:n39 | T2 | 550 | `None` | `None` | yes |
| pygments:T5:24 | T5 | 59 | `225` | `225` | yes |
| pygments:T5:24 | T5 | 84 | `226` | `226` | yes |
| pygments:T5:24 | T5 | 255 | `242` | `242` | yes |
| pygments:T5:24 | T5 | 509 | `259` | `259` | yes |
| pygments:T5:24 | T5 | 522 | `260` | `260` | yes |
| pygments:T6:30 | T6 | 105 | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | yes |
| pygments:T6:30 | T6 | 149 | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | yes |
| pygments:T6:30 | T6 | 334 | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | yes |
| pygments:T6:30 | T6 | 405 | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | yes |
| pygments:T6:30 | T6 | 415 | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | `pygments/lexers/agile.py, pygments/lexers/compiled.py, pygme` | yes |
| typer:T1:n19 | T1 | 38 | `typer/cli.py` | `typer/cli.py` | yes |
| typer:T1:n19 | T1 | 303 | `typer/cli.py` | `typer/cli.py` | yes |
| typer:T1:n19 | T1 | 398 | `typer/cli.py` | `typer/cli.py` | yes |
| typer:T1:n19 | T1 | 449 | `typer/cli.py` | `typer/cli.py` | yes |
| typer:T1:n19 | T1 | 478 | `typer/cli.py` | `typer/cli.py` | yes |
| boltons:T5:27 | T5 | 172 | `6` | `6` | yes |
| boltons:T5:27 | T5 | 179 | `6` | `6` | yes |
| boltons:T5:27 | T5 | 398 | `6` | `6` | yes |
| boltons:T5:27 | T5 | 564 | `6` | `6` | yes |
| boltons:T5:27 | T5 | 636 | `6` | `6` | yes |
| networkx:T5:26 | T5 | 264 | `47` | `47` | yes |
| networkx:T5:26 | T5 | 265 | `47` | `47` | yes |
| networkx:T5:26 | T5 | 389 | `48` | `48` | yes |
| networkx:T5:26 | T5 | 402 | `48` | `48` | yes |
| networkx:T5:26 | T5 | 439 | `48` | `48` | yes |
| jinja:T4:23 | T4 | 353 | `NONE` | `NONE` | yes |
| jinja:T4:23 | T4 | 397 | `NONE` | `NONE` | yes |
| jinja:T4:23 | T4 | 417 | `NONE` | `NONE` | yes |
| jinja:T4:23 | T4 | 494 | `NONE` | `NONE` | yes |
| jinja:T4:23 | T4 | 514 | `NONE` | `NONE` | yes |
| marshmallow:T4:18 | T4 | 20 | `NONE` | `NONE` | yes |
| marshmallow:T4:18 | T4 | 173 | `NONE` | `NONE` | yes |
| marshmallow:T4:18 | T4 | 515 | `mypy --show-error-codes --warn-unused-ignores tests/mypy_tes` | `mypy --show-error-codes --warn-unused-ignores tests/mypy_tes` | yes |
| marshmallow:T4:18 | T4 | 543 | `NONE` | `NONE` | yes |
| marshmallow:T4:18 | T4 | 677 | `NONE` | `NONE` | yes |
| kombu:T3:n2 | T3 | 28 | `self, queue, kwargs` | `self, queue, kwargs` | yes |
| kombu:T3:n2 | T3 | 229 | `self, queue, kwargs` | `self, queue, kwargs` | yes |
| kombu:T3:n2 | T3 | 277 | `self, queue, kwargs` | `self, queue, kwargs` | yes |
| kombu:T3:n2 | T3 | 471 | `self, queue, kwargs` | `self, queue, kwargs` | yes |
| kombu:T3:n2 | T3 | 500 | `self, queue, kwargs` | `self, queue, kwargs` | yes |
| pyparsing:T1:n39 | T1 | 113 | `pyparsing/exceptions.py` | `pyparsing/exceptions.py` | yes |
| pyparsing:T1:n39 | T1 | 221 | `pyparsing/exceptions.py` | `pyparsing/exceptions.py` | yes |
| pyparsing:T1:n39 | T1 | 416 | `pyparsing/exceptions.py` | `pyparsing/exceptions.py` | yes |
| pyparsing:T1:n39 | T1 | 579 | `pyparsing/exceptions.py` | `pyparsing/exceptions.py` | yes |
| pyparsing:T1:n39 | T1 | 670 | `pyparsing/exceptions.py` | `pyparsing/exceptions.py` | yes |
| jinja:B:modifies_known_mutable:281f5f09 | B | 118 | `NONE` | `NONE` | yes |
| jinja:B:modifies_known_mutable:281f5f09 | B | 144 | `NONE` | `NONE` | yes |
| jinja:B:modifies_known_mutable:281f5f09 | B | 419 | `True` | `True` | yes |
| jinja:B:modifies_known_mutable:281f5f09 | B | 583 | `True` | `True` | yes |
| jinja:B:modifies_known_mutable:281f5f09 | B | 674 | `True` | `True` | yes |
| networkx:B:is_semiconnected:n-a04022dc | B | 1 | `'True'` | `'True'` | yes |
| networkx:B:is_semiconnected:n-a04022dc | B | 152 | `'True'` | `'True'` | yes |
| networkx:B:is_semiconnected:n-a04022dc | B | 436 | `'True'` | `'True'` | yes |
| networkx:B:is_semiconnected:n-a04022dc | B | 441 | `'True'` | `'True'` | yes |
| networkx:B:is_semiconnected:n-a04022dc | B | 629 | `'True'` | `'True'` | yes |
| poetry-core:B:get_requires_for_build_wheel:3b4f8948 | B | 11 | `NONE` | `NONE` | yes |
| poetry-core:B:get_requires_for_build_wheel:3b4f8948 | B | 112 | `[]` | `[]` | yes |
| poetry-core:B:get_requires_for_build_wheel:3b4f8948 | B | 465 | `[]` | `[]` | yes |
| poetry-core:B:get_requires_for_build_wheel:3b4f8948 | B | 506 | `[]` | `[]` | yes |
| poetry-core:B:get_requires_for_build_wheel:3b4f8948 | B | 572 | `[]` | `[]` | yes |
| jinja:B:do_capitalize:a178a29a | B | 286 | `NONE` | `NONE` | yes |
| jinja:B:do_capitalize:a178a29a | B | 319 | `'Abc'` | `'Abc'` | yes |
| jinja:B:do_capitalize:a178a29a | B | 375 | `'Abc'` | `'Abc'` | yes |
| jinja:B:do_capitalize:a178a29a | B | 401 | `'Abc'` | `'Abc'` | yes |
| jinja:B:do_capitalize:a178a29a | B | 691 | `'Abc'` | `'Abc'` | yes |
| boltons:B:asciify:55eedf43 | B | 158 | `True` | `True` | yes |
| boltons:B:asciify:55eedf43 | B | 214 | `True` | `True` | yes |
| boltons:B:asciify:55eedf43 | B | 306 | `True` | `True` | yes |
| boltons:B:asciify:55eedf43 | B | 329 | `True` | `True` | yes |
| boltons:B:asciify:55eedf43 | B | 425 | `True` | `True` | yes |
| werkzeug:B:url_unparse:n-7473d0cb | B | 374 | `raises TypeError` | `raises TypeError` | yes |
| werkzeug:B:url_unparse:n-7473d0cb | B | 420 | `raises TypeError` | `raises TypeError` | yes |
| werkzeug:B:url_unparse:n-7473d0cb | B | 633 | `NONE` | `NONE` | yes |
| werkzeug:B:url_unparse:n-7473d0cb | B | 641 | `NONE` | `NONE` | yes |
| werkzeug:B:url_unparse:n-7473d0cb | B | 651 | `NONE` | `NONE` | yes |
| poetry-core:B:normalize_file_permissions:n-b8f9150a | B | 63 | `420` | `420` | yes |
| poetry-core:B:normalize_file_permissions:n-b8f9150a | B | 387 | `420` | `420` | yes |
| poetry-core:B:normalize_file_permissions:n-b8f9150a | B | 418 | `420` | `420` | yes |
| poetry-core:B:normalize_file_permissions:n-b8f9150a | B | 448 | `420` | `420` | yes |
| poetry-core:B:normalize_file_permissions:n-b8f9150a | B | 681 | `420` | `420` | yes |
| jinja:B:Template:52290b37 | B | 80 | `NONE` | `NONE` | yes |
| jinja:B:Template:52290b37 | B | 170 | `NONE` | `NONE` | yes |
| jinja:B:Template:52290b37 | B | 341 | `'Hello John Doe!'` | `'Hello John Doe!'` | yes |
| jinja:B:Template:52290b37 | B | 357 | `'Hello John Doe!'` | `'Hello John Doe!'` | yes |
| jinja:B:Template:52290b37 | B | 679 | `'Hello '` | `'Hello '` | yes |
| jinja:B:Undefined:n-340a4777 | B | 136 | `NONE` | `NONE` | yes |
| jinja:B:Undefined:n-340a4777 | B | 280 | `NONE` | `NONE` | yes |
| jinja:B:Undefined:n-340a4777 | B | 323 | `True` | `True` | yes |
| jinja:B:Undefined:n-340a4777 | B | 363 | `True` | `True` | yes |
| jinja:B:Undefined:n-340a4777 | B | 606 | `True` | `True` | yes |
| isort:B:check_code_string:n-be196cf0 | B | 186 | `True` | `True` | yes |
| isort:B:check_code_string:n-be196cf0 | B | 345 | `True` | `True` | yes |
| isort:B:check_code_string:n-be196cf0 | B | 410 | `True` | `True` | yes |
| isort:B:check_code_string:n-be196cf0 | B | 498 | `True` | `True` | yes |
| isort:B:check_code_string:n-be196cf0 | B | 586 | `True` | `True` | yes |
