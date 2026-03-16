import React, { useState } from 'react';
import './SetupWizard.css';

type Strategy = 'economy' | 'balanced' | 'quality';

const strategyConfig = {
  economy: {
    icon: '💰',
    title: 'Economy',
    description: 'Prioritizes speed and low cost using lighter models. Great for simple fixes and drafts.',
    command: 'export SPIRAL_STRATEGY="economy"',
  },
  balanced: {
    icon: '⚖️',
    title: 'Balanced',
    description: 'Smartly adapts to your task, saving money on simple jobs while using power when needed.',
    command: 'export SPIRAL_STRATEGY="balanced"',
  },
  quality: {
    icon: '💎',
    title: 'Quality',
    description: 'Uses the most powerful AI for the best results on the first try. Ideal for complex, critical work.',
    command: 'export SPIRAL_STRATEGY="quality"',
  },
};

export const SetupWizard: React.FC = () => {
  const [step, setStep] = useState(1);
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy>('balanced');

  const handleSelect = (strategy: Strategy) => {
    setSelectedStrategy(strategy);
    setStep(2);
  };

  const renderStep1 = () => (
    <div className="wizard-step">
      <h2>Choose Your AI Strategy</h2>
      <p>Select how you want Spiral to balance cost, speed, and quality.</p>
      <div className="strategy-options">
        {(Object.keys(strategyConfig) as Strategy[]).map((key) => (
          <div key={key} className="strategy-card" onClick={() => handleSelect(key)}>
            <div className="strategy-icon">{strategyConfig[key].icon}</div>
            <h3>{strategyConfig[key].title}</h3>
            <p>{strategyConfig[key].description}</p>
          </div>
        ))}
      </div>
    </div>
  );

  const renderStep2 = () => {
    const config = strategyConfig[selectedStrategy];
    return (
      <div className="wizard-step">
        <h2>Configuration Complete</h2>
        <p>You've selected the <strong>{config.title}</strong> strategy.</p>
        <p>To apply this setting, run the following command in your terminal before starting Spiral:</p>
        <div className="command-box">
          <code>{config.command}</code>
          <button onClick={() => navigator.clipboard.writeText(config.command)}>
            Copy
          </button>
        </div>
        <p>You can change this anytime by re-running the command or by setting the `SPIRAL_STRATEGY` environment variable.</p>
        <button className="back-button" onClick={() => setStep(1)}>
          &larr; Choose a different strategy
        </button>
      </div>
    );
  };

  return (
    <div className="wizard-container">
      <h1>Welcome to Spiral</h1>
      {step === 1 ? renderStep1() : renderStep2()}
    </div>
  );
};
