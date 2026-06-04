'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Send, Paperclip, Mic } from 'lucide-react';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
    }
  }, [input]);

  const handleSend = () => {
    if (input.trim() && !disabled) {
      onSend(input.trim());
      setInput('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="chat-input-container">
      <div className="chat-input-wrapper">
        <button className="icon-btn" title="Attach file">
          <Paperclip size={20} />
        </button>
        
        <textarea
          ref={textareaRef}
          className="chat-input-field"
          placeholder="Ask me about HDFC Mutual Funds..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={disabled}
        />
        
        <div className="chat-input-actions">
          {input.trim() === '' ? (
             <button className="icon-btn" title="Voice input">
               <Mic size={20} />
             </button>
          ) : (
            <button 
              className="send-btn" 
              onClick={handleSend}
              disabled={disabled || input.trim() === ''}
              title="Send message"
            >
              <Send size={18} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
