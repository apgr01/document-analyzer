"""Esecuzione parallela di un'operazione su molte pagine, con manifest.

Sia la descrizione delle pagine (RAG) sia l'indicizzazione fanno la stessa cosa:
per ogni pagina chiamano Gemini e salvano un risultato. Questo modulo raccoglie
la parte comune:

- esegue il lavoro in parallelo (un thread per chiave API, di default);
- aggiorna il manifest dopo ogni pagina (fatta / fallita);
- si ferma in modo ordinato se le quote sono esaurite o se troppe pagine di fila
  falliscono (tipico di un problema generale, es. nome del modello sbagliato:
  inutile sprecare richieste su tutte le pagine);
- con Ctrl+C si interrompe senza perdere le pagine già completate.

``run_pages`` lavora una pagina per richiesta; ``run_blocks`` lavora **gruppi di pagine**
(più pagine in una sola richiesta, vedi l'indicizzazione con invio "insieme"): il manifest
resta per pagina, e ogni pagina viene segnata appena il suo risultato è salvato.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from tqdm import tqdm

from docanalyzer.core.gemini import (
    GeminiNotConfiguredError,
    OperationCancelledError,
    QuotaExhaustedError,
    ServiceUnavailableError,
    cancellation,
)
from docanalyzer.core.manifest import Manifest

MAX_CONSECUTIVE_FAILURES = 5


@dataclass
class RunReport:
    requested: int = 0
    succeeded: int = 0
    failed: dict[int, str] = field(default_factory=dict)
    not_attempted: int = 0
    stopped_reason: str | None = None

    @property
    def completed(self) -> bool:
        return self.stopped_reason is None and not self.failed and self.not_attempted == 0


class _Stop(Exception):
    pass


@dataclass
class RunControl:
    """Collegamento con un'interfaccia: avanzamento e richiesta di annullamento.

    ``progress(fatte, totali, messaggio)`` viene chiamata dopo ogni pagina; ``cancel``
    è un evento che l'interfaccia può impostare per fermare il lavoro in modo ordinato
    (le pagine in corso terminano, le altre non partono).
    """

    progress: Callable[[int, int, str], None] | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    done: int = 0
    total: int = 0

    def report(self, done: int, total: int, message: str = "") -> None:
        self.done, self.total = done, total
        if self.progress is not None:
            self.progress(done, total, message)

    def note(self, message: str) -> None:
        """Un messaggio per l'interfaccia, senza cambiare l'avanzamento."""
        self.report(self.done, self.total, message)


def run_pages(
    pages: list[int],
    worker: Callable[[int], None],
    manifest: Manifest,
    parallelism: int,
    description: str,
    show_progress: bool = True,
    control: RunControl | None = None,
) -> RunReport:
    report = RunReport(requested=len(pages))
    if not pages:
        return report
    control = control or RunControl()

    stop = threading.Event()
    lock = threading.Lock()
    consecutive_failures = 0

    def task(n: int) -> None:
        nonlocal consecutive_failures
        if stop.is_set() or control.cancel.is_set():
            raise _Stop()
        try:
            with cancellation(control.cancel):
                worker(n)
        except OperationCancelledError as e:
            raise _Stop() from e          # fermato dall'utente: la pagina resta da fare
        except (QuotaExhaustedError, ServiceUnavailableError, GeminiNotConfiguredError) as e:
            # Non è colpa della pagina: non si conta come tentativo fallito.
            with lock:
                if report.stopped_reason is None:
                    report.stopped_reason = str(e)
            stop.set()
            raise _Stop() from e
        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            manifest.mark_failed(n, message)
            with lock:
                report.failed[n] = message
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES and report.stopped_reason is None:
                    report.stopped_reason = (
                        f"{MAX_CONSECUTIVE_FAILURES} pagine di fila sono fallite: probabile problema "
                        f"generale (chiave, modello, rete). Ultimo errore: {message}"
                    )
                    stop.set()
            raise
        else:
            manifest.mark_done(n)
            with lock:
                report.succeeded += 1
                consecutive_failures = 0

    executor = ThreadPoolExecutor(max_workers=max(1, parallelism))
    try:
        futures = {executor.submit(task, n): n for n in pages}
        done = 0
        control.report(0, len(pages), description)
        with tqdm(total=len(pages), desc=description, unit="pag", disable=not show_progress) as bar:
            for future in as_completed(futures):
                n = futures[future]
                try:
                    future.result()
                except _Stop:
                    with lock:
                        report.not_attempted += 1
                except Exception:
                    if show_progress:
                        tqdm.write(f"  Pagina {n}: {report.failed.get(n, 'errore')}")
                bar.update(1)
                done += 1
                control.report(done, len(pages), description)
    except KeyboardInterrupt:
        stop.set()
        report.stopped_reason = "interrotto dall'utente (Ctrl+C)"
        executor.shutdown(wait=True, cancel_futures=True)
        report.not_attempted = report.requested - report.succeeded - len(report.failed)
        return report
    finally:
        executor.shutdown(wait=True)

    if control.cancel.is_set() and report.stopped_reason is None and report.not_attempted:
        report.stopped_reason = "annullato dall'utente"
    return report


def run_blocks(
    blocks: list[list[int]],
    worker: Callable[[list[int], Callable[[int, str | None], None]], None],
    manifest: Manifest,
    parallelism: int,
    description: str,
    show_progress: bool = True,
    control: RunControl | None = None,
) -> RunReport:
    """Come :func:`run_pages`, ma ogni lavoro è un **gruppo di pagine** (una richiesta).

    ``worker(blocco, segna)`` chiama ``segna(pagina, None)`` per ogni pagina riuscita e
    ``segna(pagina, errore)`` per ogni pagina fallita, appena lo sa: così, se il lavoro si
    ferma a metà (quote, *Ferma*), le pagine già ottenute restano fatte. Le pagine di un
    blocco che il worker non segna risultano fallite ("non restituita").
    """
    total = sum(len(b) for b in blocks)
    report = RunReport(requested=total)
    if not total:
        return report
    control = control or RunControl()
    stop = threading.Event()
    lock = threading.Lock()
    state = {"done": 0, "consecutive": 0}
    bar = tqdm(total=total, desc=description, unit="pag", disable=not show_progress)

    def record(page: int, error: str | None) -> None:
        with lock:
            if error is None:
                manifest.mark_done(page)
                report.succeeded += 1
            else:
                manifest.mark_failed(page, error)
                report.failed[page] = error
                if show_progress:
                    tqdm.write(f"  Pagina {page}: {error}")
            state["done"] += 1
            done = state["done"]
            bar.update(1)
        control.report(done, total, description)

    def task(block: list[int]) -> None:
        if stop.is_set() or control.cancel.is_set():
            raise _Stop()
        seen: dict[int, bool] = {}

        def mark(page: int, error: str | None = None) -> None:
            if page in block and page not in seen:
                seen[page] = error is None
                record(page, error)

        control.note(f"{description}: {len(block)} pagin{'a' if len(block) == 1 else 'e'} in una richiesta")
        try:
            with cancellation(control.cancel):
                worker(block, mark)
        except OperationCancelledError as e:
            raise _Stop() from e          # fermato dall'utente: le pagine non segnate restano da fare
        except (QuotaExhaustedError, ServiceUnavailableError, GeminiNotConfiguredError) as e:
            with lock:
                if report.stopped_reason is None:
                    report.stopped_reason = str(e)
            stop.set()
            raise _Stop() from e
        except Exception as e:
            message = f"{type(e).__name__}: {e}"
            for page in block:
                mark(page, message)
        for page in block:
            mark(page, "Gemini non ha restituito questa pagina nella risposta")
        with lock:
            if any(seen.values()):
                state["consecutive"] = 0
            else:
                state["consecutive"] += 1
                if state["consecutive"] >= MAX_CONSECUTIVE_FAILURES and report.stopped_reason is None:
                    report.stopped_reason = (
                        f"{MAX_CONSECUTIVE_FAILURES} richieste di fila sono fallite: probabile problema "
                        f"generale (chiave, modello, rete). Ultimo errore: {next(iter(report.failed.values()), '')}"
                    )
                    stop.set()

    executor = ThreadPoolExecutor(max_workers=max(1, parallelism))
    try:
        control.report(0, total, description)
        futures = [executor.submit(task, block) for block in blocks]
        for future in as_completed(futures):
            try:
                future.result()
            except _Stop:
                pass
    except KeyboardInterrupt:
        stop.set()
        report.stopped_reason = "interrotto dall'utente (Ctrl+C)"
        executor.shutdown(wait=True, cancel_futures=True)
    finally:
        executor.shutdown(wait=True)
        bar.close()

    report.not_attempted = report.requested - report.succeeded - len(report.failed)
    if control.cancel.is_set() and report.stopped_reason is None and report.not_attempted:
        report.stopped_reason = "annullato dall'utente"
    return report
