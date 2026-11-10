"""Explicit provider catalog reads and a single bounded, opt-in tool-call probe.

No SDK retries, redirects, environment credentials, evaluator access, or persistence.
See docs/provider-discovery.md for the provider-specific contracts and limitations.
"""
import http.client
import json
import re
from urllib.parse import urlsplit

MODEL_PATTERN = r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}'
CATALOG_URLS = {
    'openai': 'https://api.openai.com/v1/models',
    'openrouter': 'https://openrouter.ai/api/v1/models',
    'huggingface': 'https://router.huggingface.co/v1/models',
}
INFERENCE_URLS = {
    'openai': 'https://api.openai.com/v1/responses',
    'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
    'huggingface': 'https://router.huggingface.co/v1/chat/completions',
}
OUTPUT_LIMIT = 128
TIMEOUT = 20
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MESSAGES = {
    'authentication': 'Authentication or permission denied. Check the selected provider key and account permissions.',
    'rate_limit': 'Provider rate limit or quota reached. No automatic retry was made.',
    'unavailable_model': 'Model or route unavailable. Check the model ID, account access, and routing constraints.',
    'billing': 'Provider requires credits or billing access. No automatic retry was made.',
    'invalid_request': 'Provider rejected the model or test parameters. Compatibility is unconfirmed.',
    'provider_unavailable': 'Provider unavailable or connection failed. No automatic retry was made; a test may still have been billed.',
    'invalid_response': 'Provider returned an unreadable or unexpected response. No automatic retry was made.',
}


class DiscoveryError(Exception):
    def __init__(self, state):
        self.state = state
        super().__init__(MESSAGES[state])

    def result(self):
        return {'state': self.state, 'error': MESSAGES[self.state]}


def validate(provider, key, model='', routing='price'):
    if not isinstance(provider, str) or provider not in CATALOG_URLS:
        raise ValueError('Unsupported provider')
    if not isinstance(routing, str) or routing not in ('price', 'latency', 'throughput'):
        raise ValueError('Unsupported routing policy')
    if not isinstance(key, str) or not isinstance(model, str):
        raise ValueError('Key and model must be text')
    key, model = key.strip(), model.strip()
    pattern = r'hf_[A-Za-z0-9_-]{16,1024}' if provider == 'huggingface' else r'sk-[A-Za-z0-9_-]{16,1024}'
    if key and not re.fullmatch(pattern, key):
        raise ValueError('Enter a valid key for the selected provider.')
    if model and not re.fullmatch(MODEL_PATTERN, model):
        raise ValueError('Enter a model ID without spaces or shell characters')
    return key, model


def _status_error(status):
    if status in (401, 403):
        return DiscoveryError('authentication')
    if status == 429:
        return DiscoveryError('rate_limit')
    if status in (404, 410):
        return DiscoveryError('unavailable_model')
    if status == 402:
        return DiscoveryError('billing')
    if status in (400, 422):
        return DiscoveryError('invalid_request')
    return DiscoveryError('provider_unavailable')


def request_json(method, url, key, body):
    """One HTTPS request. Fixed URLs only; http.client never follows redirects/retries."""
    if url not in tuple(CATALOG_URLS.values()) + tuple(INFERENCE_URLS.values()):
        raise ValueError('Unsupported endpoint')
    parsed = urlsplit(url)
    connection = http.client.HTTPSConnection(parsed.hostname, timeout=TIMEOUT)
    try:
        connection.request(method, parsed.path,
                           body=None if body is None else json.dumps(body).encode(),
                           headers={'Authorization': 'Bearer ' + key,
                                    'Content-Type': 'application/json', 'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            # Do not read, stringify, log, or return provider error bodies/headers.
            raise _status_error(response.status)
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise DiscoveryError('invalid_response')
        return json.loads(raw)
    except DiscoveryError:
        raise
    except (ValueError, UnicodeError):
        raise DiscoveryError('invalid_response') from None
    except (OSError, http.client.HTTPException):
        raise DiscoveryError('provider_unavailable') from None
    finally:
        connection.close()


class ProviderDiscovery:
    def __init__(self, transport=None):
        self.transport = transport or request_json

    def _request(self, method, url, key, body=None):
        try:
            result = self.transport(method, url, key, body)
        except DiscoveryError:
            raise
        except Exception:
            # Injected transports must also never leak credential-bearing exceptions.
            raise DiscoveryError('provider_unavailable') from None
        if not isinstance(result, dict):
            raise DiscoveryError('invalid_response')
        if 'error' in result:
            error = result['error']
            code = error.get('code') if isinstance(error, dict) else None
            raise _status_error(code) if type(code) is int else DiscoveryError('invalid_response')
        return result

    def load_models(self, provider, key):
        key, _ = validate(provider, key)
        if not key:
            raise ValueError('Enter or save a key for this provider first')
        response = self._request('GET', CATALOG_URLS[provider], key)
        if not isinstance(response.get('data'), list):
            raise DiscoveryError('invalid_response')
        models = {}
        for item in response['data']:
            if not isinstance(item, dict):
                continue
            model_id = item.get('id')
            if (not isinstance(model_id, str) or not re.fullmatch(MODEL_PATTERN, model_id)
                    or key in model_id):
                continue
            support, source = 'unknown', 'No tool capability metadata'
            if provider == 'openrouter' and isinstance(item.get('supported_parameters'), list):
                if 'tools' in item['supported_parameters']:
                    support, source = 'supported', 'OpenRouter supported_parameters includes tools'
            elif provider == 'huggingface':
                providers = item.get('providers')
                live = [p for p in providers if isinstance(p, dict) and p.get('status') == 'live'] if isinstance(providers, list) else []
                if live and all(p.get('supports_tools') is True for p in live):
                    support, source = 'supported', 'All listed live HF providers report supports_tools=true'
            # Only allowlisted fields leave the backend, never raw catalog metadata.
            models[model_id] = {'id': model_id, 'tool_support': support, 'tool_support_source': source}
        return {'state': 'success', 'provider': provider, 'models': sorted(models.values(), key=lambda m: m['id']),
                'message': 'Catalog loaded. Listing does not verify inference access or route availability.'}

    def test_connection(self, provider, key, model, routing='price', *, confirmed=False):
        if confirmed is not True:
            raise ValueError('Explicit confirmation of a potentially billable request is required')
        key, model = validate(provider, key, model, routing)
        if not key or not model:
            raise ValueError('A provider key and model ID are required for the test')
        function = {'name': 'godseye_connection_check', 'description': 'Acknowledge this connection check.',
                    'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}}
        prompt = 'Call godseye_connection_check once with empty arguments. Do not write text.'
        if provider == 'openai':
            body = {'model': model, 'input': [{'role': 'user', 'content': prompt}],
                    'tools': [{'type': 'function', **function, 'strict': True}],
                    'tool_choice': {'type': 'function', 'name': function['name']},
                    'parallel_tool_calls': False, 'max_output_tokens': OUTPUT_LIMIT,
                    'store': False, 'stream': False}
        else:
            body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
                    'tools': [{'type': 'function', 'function': function}], 'tool_choice': 'required',
                    'max_tokens': OUTPUT_LIMIT, 'stream': False}
            if provider == 'openrouter':
                body['provider'] = {'sort': routing, 'require_parameters': True,
                                    'data_collection': 'deny', 'allow_fallbacks': False}
        response = self._request('POST', INFERENCE_URLS[provider], key, body)
        try:
            if provider == 'openai':
                completed = response['status'] == 'completed'
                calls = [item for item in response['output'] if item.get('type') == 'function_call']
            else:
                choice = response['choices'][0]
                completed = choice.get('finish_reason') == 'tool_calls'
                calls = [call['function'] for call in choice['message'].get('tool_calls', [])
                         if call.get('type') == 'function']
            valid = (completed and len(calls) == 1 and calls[0].get('name') == function['name']
                     and json.loads(calls[0]['arguments']) == {})
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            valid = False
        return {'state': 'success' if valid else 'tool_call_unconfirmed', 'connected': True,
                'tool_call_verified': bool(valid), 'output_limit': OUTPUT_LIMIT, 'requests': 1,
                'message': ('Connection and one valid tool call verified. No tool was executed.' if valid else
                            'Provider responded, but tool calling was not verified within the small output limit. This does not prove tools are unsupported.')}
