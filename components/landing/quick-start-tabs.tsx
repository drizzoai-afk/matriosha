import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const macCommands = [
  "git clone https://github.com/drizzoai-afk/matriosha.git",
  "cd matriosha",
  "pip install -e .",
  "matriosha init",
  'matriosha remember "key" "value"',
  'matriosha recall "key"',
];

const windowsCommands = [
  "git clone https://github.com/drizzoai-afk/matriosha.git",
  "cd matriosha",
  "pip install -e .",
  "matriosha init",
  'matriosha remember "key" "value"',
  'matriosha recall "key"',
];

const pythonCommands = [
  "pip install -e .",
  "python -c \"import matriosha\"",
  'matriosha remember "key" "value"',
  'matriosha recall "key"',
];

function CommandBlock({ commands }: { commands: string[] }) {
  return (
    <Card className="border-border bg-card/70">
      <CardHeader>
        <CardTitle className="text-sm">Install Commands</CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="overflow-x-auto rounded-md border border-border/80 bg-black/40 p-4 text-xs text-cyan-200">
          {commands.join("\n")}
        </pre>
      </CardContent>
    </Card>
  );
}

export function QuickStartTabs() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Quick Start</h2>
        <p className="mt-2 text-sm text-muted-foreground">Install and run Matriosha in a few commands.</p>
      </div>

      <Tabs defaultValue="unix" className="w-full">
        <TabsList className="bg-zinc-900/80">
          <TabsTrigger value="unix">macOS / Linux</TabsTrigger>
          <TabsTrigger value="windows">Windows</TabsTrigger>
          <TabsTrigger value="python">Python</TabsTrigger>
        </TabsList>
        <TabsContent value="unix"><CommandBlock commands={macCommands} /></TabsContent>
        <TabsContent value="windows"><CommandBlock commands={windowsCommands} /></TabsContent>
        <TabsContent value="python"><CommandBlock commands={pythonCommands} /></TabsContent>
      </Tabs>
    </div>
  );
}
