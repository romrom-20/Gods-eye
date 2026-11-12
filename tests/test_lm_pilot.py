"""Offline evidence only; synthetic matching module is never a model-quality result."""
import copy
import json
import inspect
import textwrap
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from godseye.lm.spec import cases, cohort, plan, digest, PARAMETER
from godseye.lm.delta import validate, make_delta, applied, load_delta, tensor_hash, target
from godseye.lm.evaluate import run, paired, score

try:
    import torch
except ImportError:
    torch = None


def fixture():
    # Only the actual named projection exists; no pretrained tensors or model downloads.
    model = torch.nn.Module()
    model.model = torch.nn.Module()
    model.model.layers = torch.nn.ModuleList([torch.nn.Module()])
    model.model.layers[0].mlp = torch.nn.Module()
    model.model.layers[0].mlp.down_proj = torch.nn.Linear(3584, 1024, bias=False)
    with torch.no_grad():
        target(model).fill_(1)
    return model


class SpecTests(unittest.TestCase):
    def test_disjoint_and_caps(self):
        splits = [{(r['task'], r['answer']) for r in cases(s)} for s in ('train','dev','heldout')]
        self.assertFalse(splits[0] & splits[1] or splits[0] & splits[2] or splits[1] & splits[2])
        self.assertEqual(plan(), plan())
        for profile in ('smoke','pilot'):
            p = plan(profile)
            self.assertLessEqual(9*len(cohort('dev',p)), p['max_generations'])
            self.assertTrue(all(len(r['prompt'])<=p['max_prompt_chars'] for r in cases('heldout')))

    def test_dry_runs_without_optional_imports(self):
        for module in ('experiments.lm_pilot','experiments.modal_lm_pilot'):
            result = subprocess.run([sys.executable,'-S','-m', module,'--profile','smoke'],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['profile'], 'smoke')

    def test_scoring_and_regressions(self):
        self.assertEqual(score({'answer':'4'}, '4\n'),1)
        self.assertEqual(score({'answer':'4'}, 'The answer is 4'),0)
        rows = [dict(split='heldout', id='x', arm='unchanged',score=1),
                dict(split='heldout',id='x',arm='weight',score=0)]
        self.assertEqual(paired(rows,'heldout')['weight']['regressions'],1)


@unittest.skipIf(torch is None, 'optional torch required for numerical fixtures')
class NumericalTests(unittest.TestCase):
    def test_edit_reload_restoration_and_tampering(self):
        model = fixture()
        original = tensor_hash(target(model))
        a = make_delta(model, 0, 0.5)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'delta.json'
            path.write_text(json.dumps(a))
            with self.assertRaisesRegex(RuntimeError,'deliberate'):
                with applied(model, load_delta(path)):
                    self.assertTrue(torch.equal(target(model)[:,0],torch.full((1024,),0.5)))
                    self.assertTrue(torch.equal(target(model)[:,1],torch.ones(1024)))
                    raise RuntimeError('deliberate')
            self.assertEqual(tensor_hash(target(model)), original)
        for mutate in (lambda x:x.update(column=2), lambda x:x['before'].__setitem__(0,float('inf')),
                       lambda x:x.update(revision='main'),lambda x:x.update(extra='bad')):
            bad=copy.deepcopy(a)
            mutate(bad)
            with self.assertRaises((ValueError,TypeError)):
                validate(bad)
        with torch.no_grad():
            target(model)[0,2]=2
        with self.assertRaisesRegex(ValueError,'precondition'):
            with applied(model,a):
                pass

    def test_evaluator_freeze_selection_failures_and_negative_heldout(self):
        class SyntheticRuntime:
            def __init__(self, config):
                self.model=fixture()
                self.identity={'fixture':True,'pretrained_execution':False}
            def generate(self,prompt,**kwargs):
                edited = float(target(self.model)[0,0]) == 0
                dev = 'cobalt' in prompt or '3 + 3' in prompt
                # Assert the durable freeze exists before heldout is ever generated.
                if 'elm' in prompt or '5 + 5' in prompt:
                    frozen=json.loads((out/'frozen.json').read_text())
                    self_outer.assertEqual(frozen['selected_candidate'],0)
                answer = 'cobalt' if 'cobalt' in prompt else '6'
                if 'elm' in prompt: answer='elm'
                if '5 + 5' in prompt: answer='10'
                output = answer if (dev and edited) or (not dev and not edited) else 'wrong'
                return dict(output=output,generated_tokens=1,latency_seconds=0.01,termination='token_cap')
        self_outer=self
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/'run'
            result=run(out,'smoke',SyntheticRuntime)
            self.assertEqual(result['status'],'complete')
            self.assertEqual(result['heldout']['weight']['regressions'],2)
            self.assertTrue((out/'selected-delta.json').exists())
            self.assertTrue(json.loads((out/'rollback.json').read_text())['verified'])
            with self.assertRaises(FileExistsError):run(out,'smoke',SyntheticRuntime)

    def test_native_transformers_text_key_mapping_without_pretrained_weights(self):
        try:
            from transformers import Qwen3_5TextConfig, Qwen3_5ForCausalLM
            from safetensors.torch import save_file
        except ImportError:
            self.skipTest('optional pinned Transformers and safetensors required')
        config = Qwen3_5TextConfig(
            hidden_size=16, intermediate_size=32, num_hidden_layers=1,
            num_attention_heads=1, num_key_value_heads=1, head_dim=16,
            vocab_size=32, layer_types=['full_attention'], tie_word_embeddings=True,
            rope_parameters={'rope_type':'default', 'rope_theta':10000,
                             'partial_rotary_factor':1.0, 'mrope_section':[2,3,3]})
        original = Qwen3_5ForCausalLM(config)
        weights = {k.replace('model.', 'model.language_model.', 1):v.clone()
                   for k,v in original.state_dict().items() if k != 'lm_head.weight'}
        with tempfile.TemporaryDirectory() as folder:
            config.save_pretrained(folder)
            save_file(weights, str(Path(folder)/'model.safetensors'))
            # Exact native device_map API on CPU, including the missing-dependency failure.
            with patch('transformers.integrations.accelerate.is_accelerate_available', return_value=False):
                with self.assertRaisesRegex(ValueError, 'requires `accelerate`'):
                    Qwen3_5ForCausalLM.from_pretrained(
                        folder, config=config, local_files_only=True, token=False,
                        trust_remote_code=False, use_safetensors=True, device_map='cpu')
            from transformers.integrations.accelerate import check_and_set_device_map
            with patch('transformers.integrations.accelerate.os.environ', {'LOCAL_RANK':'0'}):
                self.assertEqual(check_and_set_device_map('cuda'), {'':torch.device('cuda:0')})
            loaded, info = Qwen3_5ForCausalLM.from_pretrained(
                folder, config=config, local_files_only=True, token=False,
                trust_remote_code=False, use_safetensors=True, dtype=torch.float32,
                attn_implementation='eager', device_map='cpu', output_loading_info=True,
                key_mapping={r'^model\.language_model\.':'model.'})
            self.assertEqual(next(loaded.parameters()).device.type, 'cpu')
            self.assertFalse(info['missing_keys'])
            self.assertFalse(info['unexpected_keys'])
            for name, value in original.state_dict().items():
                self.assertTrue(torch.equal(value,loaded.state_dict()[name]),name)
            with torch.inference_mode():
                self.assertTrue(torch.isfinite(loaded(torch.tensor([[1,2,3]])).logits).all())

    def test_global_budget_exhaustion_is_incomplete_and_ineligible(self):
        class Uncalled:
            def __init__(self, config): self.model=fixture(); self.identity={'fixture':True}
            def generate(self,*args,**kwargs): raise AssertionError('budget must prevent generation')
        config=plan('smoke')
        config['max_generations']=0
        with tempfile.TemporaryDirectory() as root, patch('godseye.lm.evaluate.plan', return_value=config):
            out=Path(root)/'run'
            result=run(out,'smoke',Uncalled)
            self.assertEqual(result['status'],'incomplete')
            self.assertIsNone(result['frozen']['selected_candidate'])
            rows=[json.loads(line) for line in (out/'cases.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),18)
            self.assertTrue(all(r['termination']=='budget_exhausted' and r['score']==0 for r in rows))

    def test_modal_serialized_worker_with_only_allowlisted_sources(self):
        try:
            from modal._serialization import serialize
        except ImportError:
            self.skipTest('optional pinned Modal SDK required')
        from experiments.modal_lm_pilot import make_worker, image_sources
        worker=make_worker()
        self.assertIsNone(worker.__closure__)
        self.assertEqual(inspect.getclosurevars(worker).globals,{})
        payload=serialize(worker)  # Same SDK serializer used by FunctionSourceInfo.serialized_function.
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            stage=root/'image'
            stage.mkdir()
            for local_path, remote_path in image_sources():
                destination=stage/Path(remote_path).relative_to('/root')
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(local_path.read_bytes())
            (root/'worker.bin').write_bytes(payload)
            script=textwrap.dedent("""
                import sys, json, importlib.util, socket
                from pathlib import Path
                from unittest.mock import patch
                root=Path(sys.argv[1])
                sys.path.insert(0,str(root/'image'))
                assert importlib.util.find_spec('experiments') is None
                def no_network(*args,**kwargs): raise AssertionError('network forbidden in offline preflight')
                with patch.object(socket.socket,'connect',no_network), patch.object(socket.socket,'connect_ex',no_network):
                    from modal._serialization import deserialize
                    import torch
                    import godseye.lm.runtime as runtime
                    class FixtureRuntime:
                        def __init__(self,config):
                            self.identity={'fixture':True}
                            self.model=torch.nn.Module()
                            self.model.model=torch.nn.Module()
                            self.model.model.layers=torch.nn.ModuleList([torch.nn.Module()])
                            self.model.model.layers[0].mlp=torch.nn.Module()
                            self.model.model.layers[0].mlp.down_proj=torch.nn.Linear(3584,1024,bias=False)
                        def generate(self,*args,**kwargs):
                            return dict(output='wrong',generated_tokens=1,latency_seconds=0,termination='token_cap')
                    worker=deserialize((root/'worker.bin').read_bytes(),None)
                    with patch.object(runtime,'Runtime',FixtureRuntime), patch('tempfile.mkdtemp',return_value=str(root/'work')):
                        result=worker('smoke')
                    assert result['error'] is None,result['error']
                    summary=json.loads(result['files']['summary.json'])
                    assert summary['status']=='complete' and summary['per_case_records']==18
                    assert not summary['real_model_execution']
                    assert 'experiments.modal_lm_pilot' not in sys.modules
                    assert 'experiments' not in sys.modules
                    print('ALLOWLIST_DESERIALIZE_AND_FIXTURE_RUN_OK')
            """)
            completed=subprocess.run([sys.executable,'-I','-c',script,str(root)],cwd=stage,
                                     capture_output=True,text=True,timeout=60)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertIn('ALLOWLIST_DESERIALIZE_AND_FIXTURE_RUN_OK',completed.stdout)

    def test_all_error_outcomes_preserved(self):
        class Broken:
            def __init__(self, config): self.model=fixture(); self.identity={'fixture':True}
            def generate(self,*args,**kwargs): raise RuntimeError('fixture error')
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/'run'
            result=run(out,'smoke',Broken)
            self.assertEqual(result['status'],'incomplete')
            self.assertIsNone(result['frozen']['selected_candidate'])
            rows=[json.loads(s) for s in (out/'cases.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),18)
            self.assertTrue(all(r['termination']=='error' for r in rows))


if __name__=='__main__':unittest.main()
