/*
 * This is a conceptual example of a CLI setup wizard using `clack`,
 * a modern library for building interactive command-line tools.
 *
 * To run this, you would need to install clack:
 * npm install @clack/prompts
 */

import * as p from '@clack/prompts';
import { setTimeout } from 'node:timers/promises';

// --- Type Definitions ---
type ModelPreset = 'economy' | 'balanced' | 'quality' | 'custom';

interface Config {
  preset: ModelPreset;
  models: {
    utility: string;
    production: string;
    frontier: string;
  };
  apiKey?: string;
}

// --- Main Wizard Function ---
async function setupWizard() {
  console.clear();

  p.intro(`Let's configure Spiral to balance cost and quality.`);

  // 1. Offer simple presets using the "Good, Better, Best" pattern
  const preset = await p.select<
    { value: ModelPreset; label: string; hint: string }[],
    ModelPreset
  >({
    message: 'Choose a configuration preset:',
    initialValue: 'balanced',
    options: [
      {
        value: 'economy',
        label: 'Economy',
        hint: 'Lowest cost, great for simple tasks. (Uses DeepSeek-V3)',
      },
      {
        value: 'balanced',
        label: 'Balanced',
        hint: 'Best for most development. (Uses Claude 3.5 Sonnet)',
      },
      {
        value: 'quality',
        label: 'Quality',
        hint: 'Highest quality for complex tasks. (Uses OpenAI o1-mini)',
      },
      {
        value: 'custom',
        label: 'Advanced',
        hint: 'Manually choose the model for each tier.',
      },
    ],
  });

  const config: Partial<Config> = { preset };

  // 2. Progressive Disclosure: Only show advanced options if 'custom' is selected
  if (preset === 'custom') {
    const customModels = await p.group({
      utility: () =>
        p.text({
          message: 'Model for UTILITY tier (e.g., gpt-4o-mini):',
          initialValue: 'gpt-4o-mini',
        }),
      production: () =>
        p.text({
          message: 'Model for PRODUCTION tier (e.g., claude-3-5-sonnet):',
          initialValue: 'claude-3-5-sonnet',
        }),
      frontier: () =>
        p.text({
          message: 'Model for FRONTIER tier (e.g., o1-mini):',
          initialValue: 'o1-mini',
        }),
    });
    config.models = customModels;
  } else {
    // Assign models based on the selected preset
    switch (preset) {
        case 'economy':
            config.models = { utility: 'gpt-4o-mini', production: 'deepseek-v3', frontier: 'deepseek-v3' };
            break;
        case 'balanced':
            config.models = { utility: 'gpt-4o-mini', production: 'claude-3-5-sonnet', frontier: 'claude-3-5-sonnet' };
            break;
        case 'quality':
            config.models = { utility: 'claude-3-5-sonnet', production: 'o1-mini', frontier: 'o1-mini' };
            break;
    }
  }

  // 3. Educate about costs when asking for sensitive information
  const apiKey = await p.password({
    message: 'Enter your API Key for the selected models:',
    validate: (value) => {
      if (!value) return 'Please enter an API key.';
    },
  });

  p.note(
    'You can find pricing information for these models on their respective websites.
Manage your API keys and spending limits in your provider dashboard.',
    'API Key & Costs'
  );

  config.apiKey = apiKey as string;


  // --- Finalization ---
  const s = p.spinner();
  s.start('Saving configuration...');
  await setTimeout(2000); // Simulate saving to a file
  s.stop('Configuration saved.');

  p.outro(`You're all set! Run 'spiral' to get started.`);

  console.log('
Final Configuration:');
  console.log(JSON.stringify(config, null, 2));
}

setupWizard().catch(console.error);
