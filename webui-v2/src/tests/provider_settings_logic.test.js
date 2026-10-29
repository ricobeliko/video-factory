import test from 'node:test';
import assert from 'node:assert/strict';
import { calculateProviderSettingsDiff } from '../components/System/systemLogic.js';

test('1. calculateProviderSettingsDiff: sem alterações retorna hasDiff false e payload vazio', () => {
  const initial = {
    llm: {
      provider: 'openai',
      model_name: 'gpt-4o',
      base_url: '',
      is_configured: true,
      masked_api_key: '••••9999',
    },
    upload_post: {
      enabled: false,
      auto_upload: false,
      is_configured: true,
      masked_api_key: '••••1111',
      username: 'meu_perfil',
      platforms: ['youtube', 'tiktok'],
      youtube_privacy_status: 'public',
      youtube_made_for_kids: false,
    },
  };

  const formValues = {
    llm_provider: 'openai',
    llm_api_key: '', // Vazio = não alterar
    llm_model_name: 'gpt-4o',
    llm_base_url: '',
    upload_post_enabled: false,
    upload_post_auto_upload: false,
    upload_post_api_key: '', // Vazio = não alterar
    upload_post_username: 'meu_perfil',
    upload_post_platforms: ['youtube', 'tiktok'],
    upload_post_youtube_privacy_status: 'public',
    upload_post_youtube_made_for_kids: false,
  };

  const { payload, diffItems, hasDiff } = calculateProviderSettingsDiff(initial, formValues);
  assert.equal(hasDiff, false);
  assert.equal(diffItems.length, 0);
  assert.deepEqual(payload, {});
});

test('2. calculateProviderSettingsDiff: mascaramento e chave vazia são ignorados no payload', () => {
  const initial = {
    llm: {
      provider: 'openai',
      masked_api_key: '••••abcd',
      model_name: 'gpt-4o',
    },
    upload_post: {
      masked_api_key: '••••efgh',
    },
  };

  // Testa tanto string vazia quanto máscara passada pelo form
  const formWithMasks = {
    llm_api_key: '••••abcd',
    upload_post_api_key: '••••****',
  };

  const res = calculateProviderSettingsDiff(initial, formWithMasks);
  assert.equal(res.hasDiff, false);
  assert.equal(res.payload.llm_api_key, undefined);
  assert.equal(res.payload.upload_post_api_key, undefined);
});

test('3. calculateProviderSettingsDiff: nova chave é incluída no payload e no diff sem expor valor', () => {
  const initial = {
    llm: {
      provider: 'openai',
      masked_api_key: '••••1234',
    },
    upload_post: {
      masked_api_key: '••••5678',
    },
  };

  const formValues = {
    llm_api_key: 'sk-new-super-secret-key-12345',
  };

  const { payload, diffItems, hasDiff } = calculateProviderSettingsDiff(initial, formValues);
  assert.equal(hasDiff, true);
  assert.equal(payload.llm_api_key, 'sk-new-super-secret-key-12345');
  assert.equal(diffItems.length, 1);
  assert.equal(diffItems[0].field, 'llm_api_key');
  // O desc do diff NUNCA deve conter o segredo
  assert.equal(diffItems[0].desc.includes('sk-new'), false);
  assert.equal(diffItems[0].desc, 'Nova chave informada');
});

test('4. calculateProviderSettingsDiff: detecta alterações pontuais em campos do LLM e Upload-Post', () => {
  const initial = {
    llm: {
      provider: 'openai',
      model_name: 'gpt-4o',
      base_url: '',
    },
    upload_post: {
      enabled: false,
      auto_upload: false,
      username: 'antigo_user',
      platforms: ['youtube'],
      youtube_privacy_status: 'public',
      youtube_made_for_kids: false,
    },
  };

  const formValues = {
    llm_provider: 'gemini',
    llm_model_name: 'gemini-2.5-flash',
    llm_base_url: 'https://custom.api.com/v1',
    upload_post_enabled: true,
    upload_post_auto_upload: true,
    upload_post_username: 'novo_user',
    upload_post_platforms: ['youtube', 'tiktok', 'instagram'],
    upload_post_youtube_privacy_status: 'unlisted',
    upload_post_youtube_made_for_kids: true,
  };

  const { payload, diffItems, hasDiff } = calculateProviderSettingsDiff(initial, formValues);
  assert.equal(hasDiff, true);
  assert.equal(payload.llm_provider, 'gemini');
  assert.equal(payload.llm_model_name, 'gemini-2.5-flash');
  assert.equal(payload.llm_base_url, 'https://custom.api.com/v1');
  assert.equal(payload.upload_post_enabled, true);
  assert.equal(payload.upload_post_auto_upload, true);
  assert.equal(payload.upload_post_username, 'novo_user');
  assert.deepEqual(payload.upload_post_platforms, ['youtube', 'tiktok', 'instagram']);
  assert.equal(payload.upload_post_youtube_privacy_status, 'unlisted');
  assert.equal(payload.upload_post_youtube_made_for_kids, true);

  assert.equal(diffItems.length, 9);
});
