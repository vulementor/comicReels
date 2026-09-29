using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Launcher {
    [STAThread]
    static int Main(string[] args) {
        var root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        var python = Path.Combine(root, "runtime", "python", "pythonw.exe");
        var entry = Path.Combine(root, "app", "start.py");
        try {
            if (!File.Exists(python) || !File.Exists(entry))
                throw new FileNotFoundException("Thiếu runtime của Thỏ Remix. Cần cài lại bản stable.");
            string arguments = Quote(entry);
            foreach (var arg in args) arguments += " " + Quote(arg);
            var start = new ProcessStartInfo(python, arguments) {
                WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            using (var child = Process.Start(start)) {
                child.WaitForExit();
                return child.ExitCode;
            }
        } catch (Exception ex) {
            MessageBox.Show(ex.Message, "Thỏ Remix", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }
    }
    static string Quote(string value) {
        return "\"" + System.Text.RegularExpressions.Regex.Replace(value, "(\\\\*)\"", "$1$1\\\"")
            .TrimEnd('\\') + new string('\\', value.Length - value.TrimEnd('\\').Length) +
            new string('\\', value.Length - value.TrimEnd('\\').Length) + "\"";
    }
}
