"""The answer the fake providers start from: a generator for processes.yaml.
The extract step reads every process's IRI and label from the model, as YAML
strings; the template only loops and outputs them."""

EXTRACT = '''\
import json


def extract(trig: Path, out: Path) -> dict:
    """The view model: each process's IRI and label, quoted as YAML strings."""
    model = seams.load(trig)
    processes = [
        {"iri": json.dumps(str(process.iri)), "label": json.dumps(process.label)}
        for process in sorted(model.processes, key=lambda process: str(process.iri))
    ]
    return {"model_hash": model.hash, "processes": processes}
'''

TEMPLATE = """\
# The processes of the chat app, written by hand.
processes:
[% for process in processes %]
  - iri: [[ process.iri ]]
    label: [[ process.label ]]
[% endfor %]
"""

GOLDEN = """\
# The processes of the chat app, written by hand.  # [fixed]
processes:  # [fixed]
  - iri: "https://example.org/chat/send_message_process"  # [graph: :send_message_process a proc:Process]
    label: "Send Message Process"  # [graph: :send_message_process rdfs:label]
"""

GOOD = {"extract": EXTRACT, "template": TEMPLATE, "golden": GOLDEN}
