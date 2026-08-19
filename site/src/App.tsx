import { useEffect, useState } from "react";
import { Header, Footer } from "./components/Chrome";
import Home from "./pages/Home";
import RunCheck from "./pages/RunCheck";
import Result from "./pages/Result";
import Archive from "./pages/Archive";
import Method from "./pages/Method";

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
  if (raw === "" || raw === "/") return "/";
  return raw.replace(/\/+$/, "");
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
  if (route === "/run") return <RunCheck />;
  if (route === "/archive") return <Archive />;
  if (route === "/method") return <Method />;

  const check = route.match(/^\/check\/(.+)$/);
  if (check) return <Result checkId={decodeURIComponent(check[1])} />;

  return <NotFound route={route} />;
}

function NotFound({ route }: { route: string }) {
  return (
    <div className="shell page-body" style={{ paddingTop: "5rem" }}>
      <div className="stack" style={{ gap: "1rem" }}>
        <span className="label">No such page</span>
        <h1 className="claim" style={{ fontSize: "var(--step-4)" }}>
          Nothing lives at this address.
        </h1>
        <p className="reading soft">
          The route <span className="value">{route}</span> does not exist. A
          check is at <span className="value">#/check/its-id</span>.
        </p>
        <p style={{ marginTop: "0.5rem" }}>
          <a className="textlink" href="#/archive">
            See every check on the contract
          </a>
        </p>
      </div>
    </div>
  );
}
