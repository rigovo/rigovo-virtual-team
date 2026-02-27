interface LanguagePageProps {
  selectedLanguage: string;
  availableLanguages: string[];
  onSelectLanguage: (language: string) => void;
}

export default function LanguagePage({
  selectedLanguage,
  availableLanguages,
  onSelectLanguage,
}: LanguagePageProps): JSX.Element {
  return (
    <section className="workspace-page">
      <div className="workspace-page-header">
        <h2>Language</h2>
        <p>
          Local UI preference only. Persisted in desktop local storage because no backend language API is currently exposed.
        </p>
      </div>

      <div className="workspace-stack">
        {availableLanguages.map((lang) => (
          <button
            key={lang}
            type="button"
            onClick={() => onSelectLanguage(lang)}
            className={`language-option ${selectedLanguage === lang ? "active" : ""}`}
          >
            <span>{lang}</span>
            {selectedLanguage === lang && <span>Selected</span>}
          </button>
        ))}
      </div>
    </section>
  );
}

