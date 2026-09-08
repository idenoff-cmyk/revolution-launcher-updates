import java.io.*;
import java.net.*;
import java.lang.reflect.*;
public class RangeAudit {
  public static void main(String[] args) throws Exception {
    URL[] urls = new URL[args.length];
    for (int i=0;i<args.length;i++) urls[i]=new File(args[i]).toURI().toURL();
    URLClassLoader loader = new URLClassLoader(urls);
    Class<?> vr=loader.loadClass("org.apache.maven.artifact.versioning.VersionRange");
    Class<?> av=loader.loadClass("org.apache.maven.artifact.versioning.ArtifactVersion");
    Class<?> dv=loader.loadClass("org.apache.maven.artifact.versioning.DefaultArtifactVersion");
    Method parse=vr.getMethod("createFromVersionSpec",String.class), contains=vr.getMethod("containsVersion",av);
    BufferedReader in=new BufferedReader(new InputStreamReader(System.in));
    for(String line;(line=in.readLine())!=null;) {
      String[] p=line.split("\t",-1);
      try {
        Object range=parse.invoke(null,p[1]);
        boolean ok=false;
        for (int i=2;i<p.length;i++) ok |= (Boolean)contains.invoke(range,dv.getConstructor(String.class).newInstance(p[i]));
        System.out.println(p[0]+"\t"+ok);
      } catch(Exception e) {System.out.println(p[0]+"\terror:"+e.getCause());}
    }
  }
}
