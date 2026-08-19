import { useEffect, useState } from "react";
import { Header, Footer } from "./components/Chrome";
import Home from "./pages/Home";

/**
 * Hash routing, deliberately.
 *
 * The site is served from GitHub Pages, which has no server to rewrite an
 * unknown path back to index.html. A history-API route would 404 on refresh
 * and on every link anyone shares, which for a page whose whole point is
 * linkable evidence would be a poor joke.
 */
function currentRoute(): string {
  const raw = window.location.hash.replace(/^#/, "");
  return raw === "" || raw === "/" ? "/" : raw.replace(/\/+$/, "");
}

export default function App() {
  const [route, setRoute] = useState(currentRoute);

  useEffect(() => {
    const onChange = () => {
      setRoute(currentRoute());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return (
    <>
      <Header route={route} />
      <main>{render(route)}</main>
      <Footer />
    </>
  );
}

function render(route: string) {
  if (route === "/") return <Home />;
  return <NotBuiltYet route={route} />;
}

function NotBuiltYet({ route }: { route: string }) {
  return (
    <div className="shell page-body" style={{ paddingTop: "6rem" }}>
      <div className="stack" style={{ gap: "1rem" }}>
        <span className="label">Not built yet</span>
        <h1 className="claim" style={{ fontSize: "var(--step-4)" }}>
          This page is still being written.
        </h1>
        <p className="reading soft">
          The route <span className="value">{route}</span> is planned but not
          finished. The home page and the reference check are live.
        </p>
        <p>
          <a className="textlink" href="#/">
            Back to the home page
          </a>
        </p>
      </div>
    </div>
  );
}
