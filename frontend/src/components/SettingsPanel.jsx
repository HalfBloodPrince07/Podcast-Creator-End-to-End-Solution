import { RefreshCw } from 'lucide-react';
import Card from './ui/Card';
import { Input, Select } from './ui/Input';
import Button from './ui/Button';

/**
 * SettingsPanel — legacy inline settings card.
 * Kept for backward compatibility — main app uses <SettingsDrawer/> in the TopBar.
 */
export default function SettingsPanel({
  llmUrl, setLlmUrl, llmKey, setLlmKey, llmModel, setLlmModel,
  availableModels = [], refreshModels,
}) {
  return (
    <Card padding="md">
      <div
        style={{
          fontSize: 'var(--text-md)',
          fontWeight: 600,
          marginBottom: 'var(--space-4)',
          letterSpacing: 'var(--tracking-tight)',
        }}
      >
        Quick settings
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        <Input
          label="LLM base URL"
          value={llmUrl}
          onChange={(e) => setLlmUrl(e.target.value)}
        />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-3)' }}>
          <Input
            label="API key"
            type="password"
            value={llmKey}
            onChange={(e) => setLlmKey(e.target.value)}
            optional
          />
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <Select label="Model" value={llmModel} onChange={(e) => setLlmModel(e.target.value)}>
                {availableModels.map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </Select>
            </div>
            <Button
              size="md"
              variant="secondary"
              iconLeft={<RefreshCw size={13} />}
              onClick={refreshModels}
            >
              Refresh
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
